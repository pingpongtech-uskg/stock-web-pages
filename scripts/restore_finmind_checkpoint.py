#!/usr/bin/env python3
"""Recover rolling usage and cumulative rows from trusted Actions checkpoints."""
from __future__ import annotations
import argparse
import io
import json
import math
import re
import os
import sys
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.finmind_incremental import normalize_budget_state, budget_lock
from pipeline.finmind_client import FinMindError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def merge_states(current: dict, recovered: dict) -> dict:
    if current.get('version') == 3 or recovered.get('version') == 3:
        return _merge_rolling_states(current, recovered)
    days = {**current.get('days', {})}
    for day, source in recovered.get('days', {}).items():
        existing = days.get(day, {})
        source_rank = (source.get('attempts', 0), _checkpoint_rank(recovered))
        existing_rank = (existing.get('attempts', 0), _checkpoint_rank(current))
        newest = source if source_rank > existing_rank else existing
        merged = {**newest,
                  'attempts': max(existing.get('attempts', 0), source.get('attempts', 0)),
                  'ceiling': min(existing.get('ceiling', 300), source.get('ceiling', 300))}
        days[day] = merged
    latest, older = (recovered, current) if _checkpoint_rank(recovered) > _checkpoint_rank(current) else (current, recovered)
    return {**older, **latest, 'days': days,
            'retryNotBefore': max(current.get('retryNotBefore', 0), recovered.get('retryNotBefore', 0))}


def _merge_rolling_states(current: dict, recovered: dict) -> dict:
    current = normalize_budget_state(current, time.time())
    recovered = normalize_budget_state(recovered, time.time())
    latest, older = (recovered, current) if _checkpoint_rank(recovered) > _checkpoint_rank(current) else (current, recovered)
    new, old = latest['rollingHour'], older['rollingHour']
    events = {event['id']: event for event in old['events']}
    for event in new['events']:
        if event['id'] in events and events[event['id']] != event:
            raise ValueError('conflicting checkpoint attempt identity')
        events[event['id']] = event
    debts = {item['id']: item for item in old['legacyDebt']}
    for item in new['legacyDebt']:
        before = debts.get(item['id'], item)
        debts[item['id']] = {**item, 'count': max(item['count'], before['count']),
                             'until': max(item['until'], before['until']), 'unknown': item['unknown'] or before['unknown']}
    rolling = {**old, **new, 'events': sorted(events.values(), key=lambda event: (event['at'], event['id'])),
               'legacyDebt': list(debts.values()), 'projectCap': min(new['projectCap'], old['projectCap']),
               'totalAttempts': max(new['totalAttempts'], old['totalAttempts'], len(events)),
               'retryNotBefore': max(new.get('retryNotBefore', 0), old.get('retryNotBefore', 0)),
               'lastClock': max(new.get('lastClock', 0), old.get('lastClock', 0))}
    if new.get('quotaWindowId') == old.get('quotaWindowId') and 'accountCeiling' in old and 'accountCeiling' in new:
        rolling['accountCeiling'] = min(new['accountCeiling'], old['accountCeiling'])
    return {**older, **latest, 'days': {**older['days'], **latest['days']}, 'rollingHour': rolling}


def _checkpoint_rank(state: dict) -> tuple[float, int, str]:
    day = state.get('checkpointDay') or max(state.get('days', {}), default='')
    attempts = state['rollingHour']['totalAttempts'] if state.get('version') == 3 else state.get('days', {}).get(day, {}).get('attempts', 0)
    fallback = datetime.fromisoformat(day).replace(tzinfo=ZoneInfo('Asia/Taipei')).timestamp() if day else 0.0
    timestamp = datetime.fromisoformat(state['checkpointAt']).timestamp() if state.get('checkpointAt') else fallback
    return timestamp, attempts, day


def _valid_state(state: object) -> dict:
    if not isinstance(state, dict) or type(state.get('version')) is not int or state['version'] not in {1, 2, 3} or not isinstance(state.get('days'), dict):
        raise ValueError('invalid checkpoint state schema')
    if state['version'] == 3:
        try:
            normalized = normalize_budget_state(state, time.time())
            if normalized.get('checkpointAt') is not None:
                parsed = datetime.fromisoformat(normalized['checkpointAt'])
                if parsed.tzinfo is None:
                    raise ValueError('checkpoint timestamp requires timezone')
            return normalized
        except FinMindError as exc:
            raise ValueError('invalid rolling checkpoint') from exc
    days = {}
    for day, record in state['days'].items():
        if date.fromisoformat(day).isoformat() != day or not isinstance(record, dict):
            raise ValueError('invalid checkpoint day')
        for key in ('attempts', 'ceiling'):
            value = record.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 300:
                raise ValueError('invalid checkpoint attempt ceiling')
        for key in ('projectCap', 'accountCeiling', 'accountUsed', 'accountLimit', 'windowStartedAtAttempt'):
            value = record.get(key)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                raise ValueError('invalid checkpoint quota metadata')
        if record.get('projectCap', 300) > 300 or record.get('windowStartedAtAttempt', 0) > record['attempts']:
            raise ValueError('invalid checkpoint project cap')
        if 'quotaKnown' in record and not isinstance(record['quotaKnown'], bool):
            raise ValueError('invalid checkpoint quota known flag')
        if record.get('blocked') is not None and not isinstance(record['blocked'], str):
            raise ValueError('invalid checkpoint block state')
        delay = record.get('retryAfterSeconds')
        if delay is not None and (not isinstance(delay, (int, float)) or isinstance(delay, bool) or not math.isfinite(delay) or delay < 0):
            raise ValueError('invalid checkpoint retry delay')
        normalized = {**record}
        if state['version'] == 1:
            normalized['ceiling'] = record.get('projectCap', 300)
            if record.get('quotaKnown'):
                normalized['accountCeiling'] = record['ceiling']
        days[day] = normalized
    retry = state.get('retryNotBefore', 0)
    if not isinstance(retry, (int, float)) or isinstance(retry, bool) or not math.isfinite(retry) or retry < 0:
        raise ValueError('invalid checkpoint retry date')
    day = state.get('checkpointDay')
    if day is not None and (not isinstance(day, str) or date.fromisoformat(day).isoformat() != day or day not in days):
        raise ValueError('invalid active checkpoint day')
    if state.get('checkpointAt') is not None:
        parsed = datetime.fromisoformat(state['checkpointAt'])
        if parsed.tzinfo is None:
            raise ValueError('checkpoint timestamp requires timezone')
    return {**state, 'version': 2, 'days': days}


def _valid_rows(rows: object) -> dict:
    if not isinstance(rows, dict) or any(not isinstance(key, str) or not isinstance(value, dict) or
            not isinstance(value.get('rows'), list) or any(not isinstance(row, dict) for row in value['rows']) for key, value in rows.items()):
        raise ValueError('invalid checkpoint rows schema')
    return rows


def recover_zip(cache_dir: Path, payload: bytes, day: str, *, artifact_created_at: str | None = None) -> bool:
    if len(payload) > 40_000_000:
        raise ValueError('checkpoint compressed size limit')
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        files = [item for item in archive.infolist() if not item.is_dir()]
        names = {Path(item.filename).name: item.filename for item in files}
        if len(names) != len(files) or set(names) - {'state.json', 'rows.json'}:
            raise ValueError('ambiguous checkpoint filenames')
        if any(Path(item.filename).is_absolute() or '..' in Path(item.filename).parts for item in files):
            raise ValueError('unsafe checkpoint path')
        if sum(item.file_size for item in files) > 150_000_000:
            raise ValueError('checkpoint expanded size limit')
        if 'state.json' not in names:
            return False
        state = _valid_state(json.loads(archive.read(names['state.json'])))
        if state['version'] != 3 and artifact_created_at is not None:
            existing = state.get('checkpointAt')
            if existing is None or datetime.fromisoformat(existing) < datetime.fromisoformat(artifact_created_at):
                state = {**state, 'checkpointAt': artifact_created_at}
        state_path = cache_dir / 'state.json'
        with budget_lock(state_path):
            current = _valid_state(json.loads(state_path.read_bytes())) if state_path.exists() else {'version': 2, 'days': {}}
            recovered_is_newer = _checkpoint_rank(state) > _checkpoint_rank(current)
            merged = merge_states(current, state)
            rows_path = cache_dir / 'rows.json'
            current_rows = _valid_rows(json.loads(rows_path.read_bytes())) if rows_path.exists() else {}
            recovered_rows = _valid_rows(json.loads(archive.read(names['rows.json']))) if 'rows.json' in names else {}
            merged_rows = {**recovered_rows, **current_rows} if not recovered_is_newer else {**current_rows, **recovered_rows}
            for key, row in recovered_rows.items():
                if str(row.get('fetchedAt', row.get('checkedAt', ''))) > str(current_rows.get(key, {}).get('fetchedAt', current_rows.get(key, {}).get('checkedAt', ''))):
                    merged_rows[key] = row
            for path, value in [(state_path, merged), (rows_path, merged_rows)]:
                temp = path.with_suffix('.json.tmp')
                temp.write_text(json.dumps(value, sort_keys=True), encoding='utf-8'); temp.replace(path)
        return True


def _trusted_artifact(artifact: dict, run: dict, repository: str, workflow_id: int) -> bool:
    lineage = artifact.get('workflow_run') or {}
    return (run.get('event') == 'workflow_dispatch' and run.get('head_branch') == 'main' and
            run.get('workflow_id') == workflow_id and
            (run.get('head_repository') or {}).get('full_name') == repository and
            lineage.get('id') == run.get('id') and lineage.get('head_sha') == run.get('head_sha') and
            lineage.get('head_branch') == 'main' and
            re.fullmatch(r'finmind-checkpoint-[1-9][0-9]*', str(artifact.get('name'))) is not None)


def _api(path: str, token: str) -> dict:
    request = Request('https://api.github.com' + path, headers={'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def _download(path: str, token: str) -> bytes:
    request = Request('https://api.github.com' + path, headers={'Authorization': 'Bearer ' + token})
    try:
        with build_opener(NoRedirect).open(request, timeout=30) as response:
            return _bounded_artifact(response)
    except HTTPError as exc:
        if exc.code != 302:
            raise
        signed_url = exc.headers['Location']
    _validate_storage_url(signed_url)
    # Never forward the repository token to the artifact storage host.
    with build_opener(NoRedirect).open(Request(signed_url), timeout=30) as response:
        return _bounded_artifact(response)


def _bounded_artifact(response) -> bytes:
    payload = response.read(40_000_001)
    if len(payload) > 40_000_000:
        raise ValueError('checkpoint compressed size limit')
    return payload


def _validate_storage_url(url: str) -> None:
    parsed = urlsplit(url)
    host = parsed.hostname or ''
    if (parsed.scheme != 'https' or parsed.username is not None or parsed.password is not None or
        parsed.port is not None or parsed.fragment or not parsed.path.startswith('/') or
        not re.fullmatch(r'[a-z0-9.-]+', host) or not any(host.endswith(suffix) for suffix in
        ('.blob.core.windows.net', '.actions.githubusercontent.com', '.githubusercontent.com'))):
        raise ValueError('untrusted checkpoint storage origin')


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache-dir', type=Path, required=True)
    parser.add_argument('--budget-date', required=True)
    parser.add_argument('--repository', default=os.environ.get('GITHUB_REPOSITORY', ''))
    args = parser.parse_args(argv)
    token = os.environ.get('GITHUB_TOKEN')
    if not token or not args.repository:
        print('checkpoint_restore_failed=GitHub access required', file=sys.stderr); return 1
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository):
            raise ValueError('invalid repository')
        date.fromisoformat(args.budget_date)
        workflow_id = _api(f'/repos/{args.repository}/actions/workflows/daily.yml', token)['id']
        trusted_runs = {}
        recovered = 0
        # Include the hour before civil midnight, plus one older cumulative checkpoint.
        cutoff = datetime.fromisoformat(args.budget_date).replace(tzinfo=ZoneInfo('Asia/Taipei')) - timedelta(hours=1)
        for page in range(1, 11):
            result = _api(f'/repos/{args.repository}/actions/artifacts?per_page=100&page={page}', token)
            artifacts = result.get('artifacts', [])
            stop = not artifacts
            for artifact in artifacts:
                created = datetime.fromisoformat(artifact['created_at'].replace('Z', '+00:00'))
                if artifact.get('expired') or not artifact['name'].startswith('finmind-checkpoint-'):
                    continue
                run_id = (artifact.get('workflow_run') or {}).get('id')
                if not run_id:
                    continue
                if run_id not in trusted_runs:
                    trusted_runs[run_id] = _api(f'/repos/{args.repository}/actions/runs/{run_id}', token)
                if not _trusted_artifact(artifact, trusted_runs[run_id], args.repository, workflow_id):
                    continue
                size = artifact.get('size_in_bytes')
                if size is not None and (type(size) is not int or not 0 <= size <= 40_000_000):
                    raise ValueError('checkpoint artifact metadata size limit')
                if recovered >= 20:
                    raise ValueError('checkpoint recovery download limit; supplemental requests disabled')
                raw = _download(f'/repos/{args.repository}/actions/artifacts/{artifact["id"]}/zip', token)
                if recover_zip(args.cache_dir, raw, args.budget_date, artifact_created_at=artifact['created_at']):
                    recovered += 1
                    if created < cutoff:
                        stop = True
                        break
            if stop:
                break
        else:
            raise ValueError('checkpoint listing incomplete; supplemental requests disabled')
    except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile) as exc:
        print(f'checkpoint_restore_failed={type(exc).__name__}', file=sys.stderr); return 1
    print(f'checkpoint_artifacts_recovered={recovered}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
