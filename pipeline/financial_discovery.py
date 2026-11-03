"""Conservative issuer-source discovery and explicit quarterly EPS extraction."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
import certifi
from urllib3 import HTTPSConnectionPool, Timeout
from bs4 import BeautifulSoup

MAX_DOCUMENT = 20 * 1024 * 1024
MAX_DOCS = 3
USER_AGENT = "StockScreener-Evidence/1.0 (public financial evidence)"


def _host_allowed(host: str, domains: list[str]) -> bool:
    host = host.rstrip(".").lower()
    return any(host == d.lower().lstrip(".").rstrip(".") or host.endswith("." + d.lower().lstrip(".")) for d in domains if d)


def _resolve_public_url(url: str, domains: list[str] | None = None):
    """Return parsed URL and validated DNS answers for a pinned HTTPS request."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    host = parsed.hostname.lower().rstrip(".")
    if domains is not None and not _host_allowed(host, domains):
        return None
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        answers = socket.getaddrinfo(host.encode("idna").decode("ascii"), parsed.port or 443, type=socket.SOCK_STREAM)
        addresses = [ipaddress.ip_address(item[4][0]) for item in answers]
    if not addresses or not all(address.is_global for address in addresses):
        return None
    return parsed, host, addresses


def safe_public_url(url: str, domains: list[str] | None = None, *, resolve: bool = False) -> bool:
    """Only public HTTPS endpoints; optionally bind to approved issuer domains."""
    try:
        if resolve:
            return _resolve_public_url(url, domains) is not None
        p = urlparse(url)
        if p.scheme != "https" or not p.hostname or p.username or p.password:
            return False
        host = p.hostname.lower().rstrip(".")
        if domains is not None and not _host_allowed(host, domains):
            return False
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            return True
        return all(address.is_global for address in addresses)
    except (ValueError, OSError, socket.gaierror):
        return False


def discover(stock: dict) -> dict:
    """Validate search results and rank likely investor-relations reports."""
    code = str(stock.get("code", ""))
    domains = [str(d) for d in stock.get("officialDomains", []) if d]
    sources, candidates = [], []
    seen = set()
    for item in stock.get("results", []):
        url = str(item.get("url", ""))
        if url in seen:
            continue
        seen.add(url)
        if not safe_public_url(url, domains):
            continue
        title = str(item.get("title", ""))
        text = (title + " " + url).lower()
        if not re.search(r"financial|quarter|annual|report|財務|季報|年報|財報|綜合損益", text):
            continue
        kind = "pdf" if urlparse(url).path.lower().endswith(".pdf") else "html"
        candidate = {"url": url, "title": title, "provider": item.get("provider"), "kind": kind}
        candidates.append(candidate)
    candidates.sort(key=lambda x: (0 if re.search(r"investor|ir\.|financial report|財務報告|年報|季報", (x["url"] + " " + x["title"]), re.I) else 1, x["url"]))
    return {"code": code, "sources": sources, "candidates": candidates, **({"reason": "source_not_found"} if not candidates else {})}


def _year_quarter(row: dict) -> tuple[int, int] | None:
    try:
        year, quarter = int(row.get("year")), int(row.get("quarter"))
        if year < 1911:
            year += 1911
        return (year, quarter) if 1900 <= year <= 2200 and quarter in (1, 2, 3, 4) else None
    except (TypeError, ValueError):
        return None


def plan_missing_peg(detail: dict) -> dict:
    """Plan newest-first missing EPS periods from healthInputs.incomeQuarterly."""
    health = detail.get("healthInputs", {}) or {}
    rows = health.get("incomeQuarterly", []) or []
    existing: set[tuple[int, int]] = set()
    declared: set[tuple[int, int]] = set()
    for row in rows:
        if row.get("periodType", "quarter") != "quarter":
            continue
        period = _year_quarter(row)
        if period:
            declared.add(period)
            if isinstance(row.get("eps"), (int, float)) and not isinstance(row.get("eps"), bool):
                existing.add(period)
    now = datetime.now()
    calendar_period = (now.year, (now.month - 1) // 3 + 1)
    latest = max(declared | {calendar_period})
    year, quarter = latest
    requests_ = []
    for _ in range(8):
        if (year, quarter) not in existing:
            requests_.append({"period": f"{year}-Q{quarter}", "fiscalYear": year, "quarter": quarter, "required": "explicit_quarter_eps", "declaredInDetail": (year, quarter) in declared})
        quarter -= 1
        if quarter == 0:
            year -= 1
            quarter = 4
    return {"reason": "missing_explicit_quarter_eps" if requests_ else None, "requests": requests_}


def _period(text: str) -> tuple[int, int] | None:
    # Require an explicit quarter marker, accepting Gregorian or ROC year.
    m = re.search(r"(?<!\d)(20\d{2}|\d{2,3})\s*(?:年|[-/.])\s*(?:第\s*)?([1-4])\s*(?:季|季度|Q\b)", text, re.I)
    if not m:
        m = re.search(r"\b(20\d{2})\s*[-/]\s*Q([1-4])\b", text, re.I)
    if not m:
        return None
    year, q = int(m.group(1)), int(m.group(2))
    return (year + 1911 if year < 1911 else year, q)


def _identity_present(text: str, *, code: str | None, legal_name: str | None) -> bool:
    compact_text = re.sub(r"\s+", "", text)
    compact_legal_name = re.sub(r"\s+", "", legal_name or "")
    if compact_legal_name and compact_legal_name in compact_text:
        return True
    if code and code.strip():
        code_label = r"(?:股票|證券|证券|公司)\s*代號|(?:stock\s*code|ticker)"
        return re.search(rf"{code_label}\s*[:：#-]?\s*(?<!\d){re.escape(code.strip())}(?!\d)", text, re.I) is not None
    return False


def _table_currency(text: str) -> str:
    mentions = set()
    if re.search(r"\bTWD\b|\bNTD\b|NT\s*\$|新臺幣|新台幣", text, re.I):
        mentions.add("TWD")
    currency_patterns = {
        "USD": r"\bUSD\b|US\s*\$|美元", "CNY": r"\bCNY\b|RMB|人民幣|人民币",
        "JPY": r"\bJPY\b|日圓|日元", "HKD": r"\bHKD\b|HK\s*\$|港幣|港币",
        "EUR": r"\bEUR\b|€|歐元|欧元", "GBP": r"\bGBP\b|£|英鎊|英镑",
    }
    for currency, pattern in currency_patterns.items():
        if re.search(pattern, text, re.I):
            mentions.add(currency)
    return next(iter(mentions)) if len(mentions) == 1 else "unknown"


def extract_explicit_eps(html_or_text: str, *, source_url: str, sha256: str, published_date: str | None = None, code: str | None = None, legal_name: str | None = None) -> list[dict]:
    """Extract explicit-quarter EPS rows only after issuer identity is confirmed."""
    soup = BeautifulSoup(html_or_text, "html.parser")
    document_text = soup.get_text(" ", strip=True)
    if not _identity_present(document_text, code=code, legal_name=legal_name):
        return []
    out = []
    for table in soup.find_all("table"):
        table_text = " ".join(table.stripped_strings)
        if re.search(r"YTD|cumulative|累計|累计|上半年|前三季|前九個月", table_text, re.I):
            continue
        period = _period(table_text)
        if not period:
            continue
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            label = " ".join(cells[:2])
            if not re.search(r"每股盈餘|每股收益|earnings per share|\bEPS\b", label, re.I):
                continue
            basis = "diluted" if re.search(r"稀釋|diluted", label, re.I) else "basic" if re.search(r"基本|basic", label, re.I) else None
            if not basis:
                continue
            numbers = []
            for cell in cells[1:]:
                m = re.fullmatch(r"\(?\s*(-?\d[\d,]*(?:\.\d+)?)\s*\)?", cell)
                if m:
                    value = float(m.group(1).replace(",", ""))
                    if cell.strip().startswith("("):
                        value = -value
                    numbers.append(value)
            if len(numbers) != 1:
                continue
            currency = _table_currency(table_text)
            out.append({"period": f"{period[0]}-Q{period[1]}", "eps": numbers[0], "currency": currency, "scope": "consolidated" if re.search(r"合併|consolidated", table_text, re.I) else "unknown", "epsKind": basis, "sourceUrl": source_url, "pageNumber": None, "quotedRow": " | ".join(cells), "sha256": sha256, "publishedDate": published_date})
    return out


def fetch_document(url: str, domains: list[str]) -> tuple[bytes, str]:
    current_url = url
    for redirect_count in range(3):
        resolved = _resolve_public_url(current_url, domains)
        if resolved is None:
            raise ValueError("unsafe_or_unapproved_url" if redirect_count == 0 else "unsafe_redirect")
        parsed, host, addresses = resolved
        address = addresses[0].compressed
        port = parsed.port or 443
        hostname = host.encode("idna").decode("ascii")
        pool = HTTPSConnectionPool(
            address,
            port=port,
            server_hostname=hostname,
            assert_hostname=hostname,
            cert_reqs="CERT_REQUIRED",
            ca_certs=certifi.where(),
        )
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        host_header = hostname if port == 443 else f"{hostname}:{port}"
        if ":" in hostname and not hostname.startswith("["):
            host_header = f"[{hostname}]" + (f":{port}" if port != 443 else "")
        try:
            response = pool.request(
                "GET", path,
                headers={"User-Agent": USER_AGENT, "Host": host_header},
                assert_same_host=False,
                preload_content=False,
                redirect=False,
                retries=False,
                timeout=Timeout(connect=8, read=20),
            )
            if response.status in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                response.close()
                pool.close()
                if not location or redirect_count == 2:
                    raise ValueError("redirect_limit_exceeded")
                current_url = requests.compat.urljoin(current_url, location)
                continue
            if response.status >= 400:
                raise ValueError("document_fetch_failed")
            chunks, size = [], 0
            for chunk in response.stream(65536, decode_content=True):
                size += len(chunk)
                if size > MAX_DOCUMENT:
                    raise ValueError("document_too_large")
                chunks.append(chunk)
            body = b"".join(chunks)
            return body, hashlib.sha256(body).hexdigest()
        finally:
            if "response" in locals():
                response.close()
            pool.close()
    raise ValueError("redirect_limit_exceeded")


def parse_document(body: bytes, url: str, sha256: str, *, code: str, legal_name: str) -> list[dict]:
    if body.startswith(b"%PDF"):
        import pdfplumber
        from io import BytesIO
        results = []
        with pdfplumber.open(BytesIO(body)) as pdf:
            if len(pdf.pages) > 60:
                raise ValueError("pdf_page_limit_exceeded")
            document_text = " ".join(page.extract_text() or "" for page in pdf.pages)
            if not _identity_present(document_text, code=code, legal_name=legal_name):
                return []
            for page_no, page in enumerate(pdf.pages, 1):
                html = "".join("<table>" + "".join("<tr>" + "".join("<td>" + (cell or "") + "</td>" for cell in row) + "</tr>" for row in table) + "</table>" for table in (page.extract_tables() or []))
                page_records = extract_explicit_eps(html, source_url=url, sha256=sha256, code=code, legal_name=legal_name)
                for record in page_records:
                    record["pageNumber"] = page_no
                results.extend(page_records)
        return results
    return extract_explicit_eps(body.decode("utf-8", errors="replace"), source_url=url, sha256=sha256, code=code, legal_name=legal_name)


def merge_eps(detail: dict, records: list[dict]) -> dict:
    """Fill missing EPS in matching health-input quarters with evidenced metadata."""
    out = json.loads(json.dumps(detail))
    health = out.setdefault("healthInputs", {})
    rows = list(health.get("incomeQuarterly", []) or [])
    indices: dict[tuple[int, int], list[int]] = {}
    for i, row in enumerate(rows):
        period = _year_quarter(row)
        if period and row.get("periodType", "quarter") == "quarter":
            indices.setdefault(period, []).append(i)
    grouped: dict[tuple[int, int], list[dict]] = {}
    for rec in records:
        m = re.fullmatch(r"(\d{4})-Q([1-4])", str(rec.get("period", "")))
        if not m or not isinstance(rec.get("eps"), (int, float)) or isinstance(rec.get("eps"), bool):
            continue
        grouped.setdefault((int(m.group(1)), int(m.group(2))), []).append(rec)
    for period, matches in grouped.items():
        # Differing EPS values or EPS kinds for a period need human adjudication.
        if len({(r.get("eps"), r.get("epsKind")) for r in matches}) != 1:
            continue
        rec = matches[0]
        currency, scope = rec.get("currency"), rec.get("scope")
        if currency in (None, "", "unknown") or scope in (None, "", "unknown"):
            continue
        existing_indices = indices.get(period, [])
        if existing_indices:
            # Do not overwrite a value or create duplicate quarter rows.
            if len(existing_indices) != 1:
                continue
            idx = existing_indices[0]
            row = dict(rows[idx])
            if row.get("eps") is not None:
                continue
            if row.get("amountUnit") and row["amountUnit"] != currency:
                continue
            if row.get("statementScope") and row["statementScope"] != scope:
                continue
            row.update({"eps": rec["eps"], "epsKind": rec.get("epsKind"), "source": rec.get("source", "issuer_document"), "sourceUrl": rec.get("sourceUrl"), "epsEvidence": {k: rec.get(k) for k in ("pageNumber", "quotedRow", "sha256", "publishedDate", "observedAt")}})
            rows[idx] = row
            continue
        rows.append({"year": period[0], "quarter": period[1], "periodType": "quarter", "eps": rec["eps"], "currency": currency, "statementScope": scope, "epsKind": rec.get("epsKind"), "inputOrigin": "reported", "source": rec.get("source", "issuer_document"), "sourceUrl": rec.get("sourceUrl"), "epsEvidence": {k: rec.get(k) for k in ("pageNumber", "quotedRow", "sha256", "publishedDate", "observedAt")}})
    health["incomeQuarterly"] = rows
    return out
