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
]

EXCLUDE_PHRASES = [
    "patient story",
    "personal story",
    "living with",
    "celebrity",
    "awareness",
    "lifestyle",
]


@dataclass
class Item:
    title: str
    url: str
    match: str


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


def match_term(text: str, terms: List[str]) -> str:
    lower = text.lower()
    for term in terms:
        if term.lower() in lower:
            return term
    return ""


def has_signal(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in INCLUDE_SIGNAL_TERMS)


def is_excluded(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in EXCLUDE_PHRASES)


def parse_date_from_text(text: str) -> Optional[datetime]:
    m = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", text)
    if not m:
        return None
    year, month, day = map(int, m.groups())
    return datetime(year, month, day, tzinfo=timezone.utc)


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
            lines.append(f"- {item.url}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate AFib CI report from browser-collected URLs")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Input file with title<TAB>url or url")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output markdown report path")
    parser.add_argument("--days", type=int, default=10, help="Lookback window for URL/title dates")
    parser.add_argument("--allow-keyword-only", action="store_true", help="Allow matches without tracked terms")
    parser.add_argument("--no-conference-mode", action="store_true", help="Disable automatic conference-mode window")
    parser.add_argument("--fetch-missing-titles", action="store_true", help="Fetch page title for url-only lines")
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
    require_tracked = not args.allow_keyword_only and not conference_mode_active
    out: List[Item] = []

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
        if date is not None and date < cutoff:
            continue

        term_match = match_term(hay, terms)
        if require_tracked and not term_match:
            continue
        if not term_match and not has_signal(hay):
            continue

        out.append(Item(title=title, url=url, match=term_match or "Keyword-only"))

    report = render_report(out, output_path)
    output_path.write_text(report)
    print(f"Wrote report to {output_path}")
    print(f"Matched items: {len(out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
