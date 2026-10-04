from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_producer_serializes_bounded_data_only_git_custody():
    text = (ROOT / '.github/workflows/ownership.yml').read_text()
    assert 'group: ownership-state-writer' in text and 'cancel-in-progress: false' in text
    assert '--max-requests 20 --max-runtime-seconds 180' in text
    assert 'git commit-tree' in text and 'git push origin "$NEXT":refs/heads/chip-state' in text
    assert '--force' not in text and 'git checkout chip-state' not in text
    assert 'readback' in text and 'snapshot.json' in text


def test_daily_pins_one_generation_and_preserves_both_refreshes():
    text = (ROOT / '.github/workflows/daily.yml').read_text()
    assert 'scripts/fetch_ownership.py' not in text and 'ownership-reference-v1' not in text
    for line in text.splitlines():
        if 'scripts/refresh_snapshot.py' in line:
            assert '--ownership-snapshot .cache/ownership_snapshot.json' in line
    assert 'ownership_recompute' in text and '--ownership-recompute' in text
    assert 'ownership_generation' in text
