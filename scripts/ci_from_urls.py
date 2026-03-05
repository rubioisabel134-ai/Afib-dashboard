#!/usr/bin/env python3
import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
AFIB_PATH = ROOT / "data" / "afib.json"
DEFAULT_INPUT = ROOT / "data" / "ci_manual_urls.txt"
DEFAULT_OUTPUT = ROOT / "reports" / "ci_manual_scan.md"
DATE_CACHE_PATH = ROOT / "data" / "ci_date_cache.json"

CONFERENCE_MODE_DATES = [
    (2, 1, 2, 20),
    (3, 15, 4, 10),
    (5, 5, 5, 31),
    (6, 5, 6, 30),
    (8, 15, 9, 10),
]

INCLUDE_SIGNAL_TERMS = [
    "trial",
    "study",
    "phase",
    "pivotal",
    "registrational",
    "approval",
    "approved",
    "fda",
    "ema",
    "ce mark",
    "pma",
    "510(k)",
    "ide",
    "device",
    "drug",
    "catheter",
    "ablation",
    "laao",
    "left atrial appendage",
    "stroke prevention",
    "atrial fibrillation",
    "afib",
    "pfa",
    "spaf",
    "stroke prevention",
    "left atrial appendage closure",
    "watchman",
    "amulet",
    "factor xi",
    "fxi",
    "fxia",
    "antiarrhythmic",
]

EMERGING_PRODUCT_TERMS = [
    "lambre ii",
    "lambre",
    "harbor-af",
    "budiodarone",
    "milvexian",
    "abelacimab",
    "hbi-3000",
    "ap31969",
    "factor xi inhibitor",
    "fxi inhibitor",
]

DEVELOPMENT_SIGNAL_TERMS = [
    "pipeline",
    "development",
    "investigational",
    "phase 1",
    "phase 2",
    "phase 3",
    "pivotal",
    "registrational",
    "trial",
    "study",
    "late-breaking",
    "readout",
    "topline",
    "results",
    "approval",
    "approved",
    "fda",
    "ema",
    "ce mark",
    "pma",
    "510(k)",
    "ide",
]

EXCLUDE_PHRASES = [
    "patient story",
    "personal story",
    "living with",
    "celebrity",
    "awareness",
    "lifestyle",
    "how do i find treatment",
    "how to find treatment",
    "treatment options",
    "what is atrial fibrillation",
    "symptoms",
    "diagnosis",
    "support group",
    "caregiver",
    "wellness",
    "diet",
    "exercise tips",
]


@dataclass
class Item:
    title: str
    url: str
    match: str
    date: str


def load_terms() -> List[str]:
    if not AFIB_PATH.exists():
        return []
    data = json.loads(AFIB_PATH.read_text())
    terms: List[str] = []
    for item in data.get("items", []):
        name = (item.get("name") or "").strip()
        company = (item.get("company") or "").strip()
        if name:
            terms.append(name)
        if company:
            terms.append(company)
    seen = set()
    out = []
    for term in terms:
        clean = term.replace("(", "").replace(")", "").replace("\"", "").strip()
        if clean and clean not in seen:
            seen.add(clean)
            out.append(clean)
    return out


def parse_input_line(line: str) -> Optional[Tuple[str, str]]:
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    if "\t" in text:
        left, right = text.split("\t", 1)
        title = left.strip()
        url = right.strip()
        if url.startswith("http"):
            return (title, url)
    if text.startswith("http"):
        return ("", text)
    return None


def title_from_url(url: str) -> str:
    slug = url.rstrip("/").split("/")[-1]
    if not slug:
        return url
    slug = re.sub(r"[-_]+", " ", slug)
    slug = re.sub(r"\d+", "", slug).strip()
    return slug if slug else url


def fetch_title(url: str) -> Optional[str]:
    try:
        req = Request(url, headers={"User-Agent": "AFib-CI-Manual/1.0"})
        with urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return None
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if not m:
        return None
    title = re.sub(r"\s+", " ", m.group(1)).strip()
    return title if title else None


def fetch_page_date(url: str) -> Optional[datetime]:
    try:
        req = Request(url, headers={"User-Agent": "AFib-CI-Manual/1.0"})
        with urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return None

    patterns = [
        r'article:published_time"\s*content="([^"]+)"',
        r'article:modified_time"\s*content="([^"]+)"',
        r'property="og:updated_time"\s*content="([^"]+)"',
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'"dateModified"\s*:\s*"([^"]+)"',
        r'<time[^>]*datetime="([^"]+)"',
    ]
    for pattern in patterns:
        m = re.search(pattern, html, re.I)
        if not m:
            continue
        dt = parse_iso_datetime(m.group(1))
        if dt is not None:
            return dt
    return None


def fetch_ctgov_last_update(nct_id: str) -> Optional[datetime]:
    api_url = f"https://clinicaltrials.gov/api/v2/studies/{nct_id}"
    try:
        req = Request(api_url, headers={"User-Agent": "AFib-CI-Manual/1.0"})
        with urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception:
        return None

    status = payload.get("protocolSection", {}).get("statusModule", {})
    last = (
        status.get("lastUpdatePostDateStruct", {}).get("date")
        or status.get("primaryCompletionDateStruct", {}).get("date")
        or status.get("completionDateStruct", {}).get("date")
    )
    return parse_iso_datetime(last) if last else None


def parse_iso_datetime(raw: str) -> Optional[datetime]:
    text = (raw or "").strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def extract_nct_id(text: str) -> str:
    m = re.search(r"\bNCT\d{8}\b", (text or "").upper())
    return m.group(0) if m else ""


def match_term(text: str, terms: List[str]) -> str:
    lower = text.lower()
    for term in terms:
        if term.lower() in lower:
            return term
    return ""


def match_emerging_term(text: str) -> str:
    lower = text.lower()
    for term in EMERGING_PRODUCT_TERMS:
        if term in lower:
            return term
    return ""


def has_signal(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in INCLUDE_SIGNAL_TERMS)


def has_development_signal(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in DEVELOPMENT_SIGNAL_TERMS)


def is_excluded(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in EXCLUDE_PHRASES)


def parse_date_from_text(text: str) -> Optional[datetime]:
    s = text or ""

    # 2026-03-05 or 2026/03/05
    m = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", s)
    if m:
        year, month, day = map(int, m.groups())
        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except Exception:
            pass

    # 03/05/2026 or 3-5-2026
    m = re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](20\d{2})\b", s)
    if m:
        month, day, year = map(int, m.groups())
        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except Exception:
            pass

    # Month-name formats: February 10, 2026 / Feb 10, 2026 / 10 February 2026
    months = {
        "jan": 1, "january": 1,
        "feb": 2, "february": 2,
        "mar": 3, "march": 3,
        "apr": 4, "april": 4,
        "may": 5,
        "jun": 6, "june": 6,
        "jul": 7, "july": 7,
        "aug": 8, "august": 8,
        "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10,
        "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }
    m = re.search(
        r"\b("
        r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
        r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
        r")\s+(\d{1,2}),?\s+(20\d{2})\b",
        s,
        flags=re.IGNORECASE,
    )
    if m:
        mon_s, day_s, year_s = m.groups()
        month = months.get(mon_s.lower())
        if month:
            try:
                return datetime(int(year_s), month, int(day_s), tzinfo=timezone.utc)
            except Exception:
                pass

    m = re.search(
        r"\b(\d{1,2})\s+("
        r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
        r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
        r"),?\s+(20\d{2})\b",
        s,
        flags=re.IGNORECASE,
    )
    if m:
        day_s, mon_s, year_s = m.groups()
        month = months.get(mon_s.lower())
        if month:
            try:
                return datetime(int(year_s), month, int(day_s), tzinfo=timezone.utc)
            except Exception:
                pass

    return None


def parse_year_from_text(text: str) -> Optional[int]:
    years = [int(x) for x in re.findall(r"\b(20\d{2})\b", text)]
    if not years:
        return None
    # Use the newest year token if multiple years appear in a URL/title.
    return max(years)


def in_conference_window(now: datetime) -> bool:
    for start_m, start_d, end_m, end_d in CONFERENCE_MODE_DATES:
        start = datetime(now.year, start_m, start_d, tzinfo=timezone.utc)
        end = datetime(now.year, end_m, end_d, tzinfo=timezone.utc)
        if start <= now <= end:
            return True
    return False


def render_report(items: List[Item], output: Path) -> str:
    now = datetime.now(timezone.utc)
    lines = [
        f"# AFib CI Manual Scan ({now.date().isoformat()})",
        "",
        f"Run time: {now.isoformat()}",
        "",
    ]
    if not items:
        lines.append("No matching items found.")
        return "\n".join(lines) + "\n"

    lines.append("## Top Items")
    for item in items[:15]:
        lines.append(f"- {item.title} (match: {item.match})")
        lines.append(f"- Date: {item.date}")
        lines.append(f"- {item.url}")
    lines.append("")

    grouped: Dict[str, List[Item]] = {}
    for item in items:
        grouped.setdefault(item.match or "Unspecified", []).append(item)

    lines.append("## By Drug/Device")
    for key in sorted(grouped.keys(), key=lambda s: s.lower()):
        lines.append(f"- {key}")
        for item in grouped[key]:
            lines.append(f"- {item.title}")
            lines.append(f"- Date: {item.date}")
            lines.append(f"- {item.url}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def load_date_cache() -> Dict[str, str]:
    if not DATE_CACHE_PATH.exists():
        return {}
    try:
        data = json.loads(DATE_CACHE_PATH.read_text())
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def save_date_cache(cache: Dict[str, str]) -> None:
    DATE_CACHE_PATH.write_text(json.dumps(cache, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate AFib CI report from browser-collected URLs")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Input file with title<TAB>url or url")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output markdown report path")
    parser.add_argument("--days", type=int, default=10, help="Lookback window for URL/title dates")
    parser.add_argument("--allow-keyword-only", action="store_true", help="Allow matches without tracked terms")
    parser.add_argument("--no-conference-mode", action="store_true", help="Disable automatic conference-mode window")
    parser.add_argument("--fetch-missing-titles", action="store_true", help="Fetch page title for url-only lines")
    parser.add_argument("--verify-page-dates", action="store_true", help="Fetch page metadata date to enforce recency")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    if not input_path.exists():
        print(f"Missing input file: {input_path}")
        return 1

    terms = load_terms()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=args.days)
    conference_mode_active = (not args.no_conference_mode) and in_conference_window(now)
    require_tracked = not args.allow_keyword_only
    out: List[Item] = []
    date_cache = load_date_cache()
    ctgov_cache: Dict[str, str] = {}

    for raw in input_path.read_text().splitlines():
        parsed = parse_input_line(raw)
        if not parsed:
            continue
        title, url = parsed
        if not title:
            if args.fetch_missing_titles:
                fetched = fetch_title(url)
                title = fetched or title_from_url(url)
            else:
                title = title_from_url(url)

        hay = f"{title} {url}"
        if is_excluded(hay):
            continue

        date = parse_date_from_text(hay)
        item_date: Optional[datetime] = date
        if date is not None and date < cutoff:
            continue
        if date is None:
            year = parse_year_from_text(hay)
            if year is not None and year < cutoff.year:
                continue
            if args.verify_page_dates:
                cached = date_cache.get(url)
                page_date = parse_iso_datetime(cached) if cached else None
                if page_date is None:
                    page_date = fetch_page_date(url)
                    if page_date is not None:
                        date_cache[url] = page_date.isoformat()
                if page_date is not None and page_date < cutoff:
                    continue
                if page_date is not None:
                    item_date = page_date

        if item_date is None:
            nct = extract_nct_id(hay)
            if nct:
                cached_ct = ctgov_cache.get(nct)
                ct_date = parse_iso_datetime(cached_ct) if cached_ct else fetch_ctgov_last_update(nct)
                if ct_date is not None:
                    ctgov_cache[nct] = ct_date.isoformat()
                    item_date = ct_date

        term_match = match_term(hay, terms)
        emerging_match = match_emerging_term(hay)
        if require_tracked and not term_match and not emerging_match:
            continue
        if not term_match and not emerging_match and not has_signal(hay):
            continue
        if not has_development_signal(hay):
            continue

        out.append(
            Item(
                title=title,
                url=url,
                match=term_match or emerging_match or "Keyword-only",
                date=(
                    item_date.date().isoformat()
                    if item_date is not None
                    else f"Captured {now.date().isoformat()} (publish date unavailable)"
                ),
            )
        )

    report = render_report(out, output_path)
    output_path.write_text(report)
    if args.verify_page_dates:
        save_date_cache(date_cache)
    print(f"Wrote report to {output_path}")
    print(f"Matched items: {len(out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
