#!/usr/bin/env python3
import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
WATCHLIST_PATH = ROOT / "data" / "ci_watchlists.json"
AFIB_PATH = ROOT / "data" / "afib.json"
CACHE_PATH = ROOT / "data" / "ci_scan_cache.json"
REPORT_PATH = ROOT / "reports" / "ci_scan.md"

CONFERENCE_MODE_DATES = [
    # (start_month, start_day, end_month, end_day) UTC window
    (2, 1, 2, 20),   # AF Symposium (early Feb + buffer)
    (3, 15, 4, 10),  # ACC late March / early April + buffer
    (5, 5, 5, 31),   # HRS May + buffer
    (6, 5, 6, 30),   # EHRA June + buffer
    (8, 15, 9, 10),  # ESC late Aug / early Sep + buffer
]

DEFAULT_KEYWORDS = [
    "atrial fibrillation",
    "afib",
    "left atrial appendage",
    "laa",
    "laao",
    "pulsed field",
    "pfa",
    "catheter ablation",
    "antiarrhythmic",
    "factor xi",
    "factor xia",
    "stroke prevention",
]

GOOGLE_NEWS_BASE = "https://news.google.com/search?q={query}&hl=en-US&gl=US&ceid=US:en"
GOOGLE_NEWS_RSS_BASE = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

EXCLUDE_PHRASES = [
    "patient story",
    "personal story",
    "living with",
    "celebrity",
    "athlete",
    "awareness",
    "heart month",
    "tips for",
    "lifestyle",
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
]


@dataclass
class LinkItem:
    title: str
    url: str
    match: str


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: List[Tuple[str, str]] = []
        self._href: Optional[str] = None
        self._text_parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() != "a":
            return
        href = None
        for key, value in attrs:
            if key.lower() == "href" and value:
                href = value.strip()
                break
        if href:
            self._href = href
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._href is None:
            return
        text = data.strip()
        if text:
            self._text_parts.append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a":
            return
        if self._href is None:
            return
        text = " ".join(self._text_parts).strip()
        if text:
            self.links.append((text, self._href))
        self._href = None
        self._text_parts = []


def fetch_html(url: str) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": "AFib-CI-Scan/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.8",
        },
    )
    with urlopen(req, timeout=25) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def fetch_xml(url: str) -> bytes:
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.8",
        },
    )
    with urlopen(req, timeout=25) as resp:
        return resp.read()


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
    cleaned = []
    for term in terms:
        term = term.replace("(", "").replace(")", "").replace("\"", "").strip()
        if not term or term in seen:
            continue
        seen.add(term)
        cleaned.append(term)
    return cleaned


def normalize_url(base: str, link: str) -> Optional[str]:
    if not link:
        return None
    link = link.strip()
    if link.startswith("mailto:") or link.startswith("javascript:"):
        return None
    absolute = urljoin(base, link)
    parsed = urlparse(absolute)
    if not parsed.scheme.startswith("http"):
        return None
    return absolute


def match_term(text: str, terms: List[str]) -> str:
    text_lower = text.lower()
    for term in terms:
        if term.lower() in text_lower:
            return term
    return ""


def has_excluded_phrase(text: str) -> bool:
    text_lower = text.lower()
    return any(phrase in text_lower for phrase in EXCLUDE_PHRASES)


def has_include_signal(text: str) -> bool:
    text_lower = text.lower()
    return any(term in text_lower for term in INCLUDE_SIGNAL_TERMS)


def parse_date_from_text(text: str) -> Optional[datetime]:
    # ISO-like dates in URL or title: 2026-03-15 or 2026/03/15
    m = re.search(r"(20\\d{2})[-/](\\d{1,2})[-/](\\d{1,2})", text)
    if m:
        year, month, day = map(int, m.groups())
        return datetime(year, month, day, tzinfo=timezone.utc)

    # Month name formats: March 15, 2026
    months = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }
    m = re.search(r"(january|february|march|april|may|june|july|august|september|october|november|december)\\s+(\\d{1,2}),\\s*(20\\d{2})", text, re.I)
    if m:
        month = months[m.group(1).lower()]
        day = int(m.group(2))
        year = int(m.group(3))
        return datetime(year, month, day, tzinfo=timezone.utc)

    return None


def extract_matches(
    url: str,
    html: str,
    terms: List[str],
    keywords: List[str],
    cutoff: datetime,
    strict_date: bool,
    require_tracked: bool,
) -> List[LinkItem]:
    parser = LinkParser()
    parser.feed(html)
    matches: List[LinkItem] = []
    for title, href in parser.links:
        full_url = normalize_url(url, href)
        if not full_url:
            continue
        hay = f"{title} {full_url}"
        if has_excluded_phrase(hay):
            continue
        term_match = match_term(hay, terms)
        keyword_match = match_term(hay, keywords)
        if require_tracked and not term_match:
            continue
        if not term_match and not keyword_match:
            continue
        if not term_match and not has_include_signal(hay):
            continue
        date = parse_date_from_text(hay)
        if date is None:
            if strict_date:
                continue
        else:
            if date < cutoff:
                continue
        match = term_match or keyword_match
        matches.append(LinkItem(title=title, url=full_url, match=match))
    return matches


def google_news_query(label: str, days: int, domain: Optional[str] = None) -> str:
    base = f"\"{label}\" (atrial fibrillation OR AFib OR LAAO OR ablation OR device OR drug) when:{days}d"
    if domain:
        base = f"site:{domain} {base}"
    return GOOGLE_NEWS_BASE.format(query=quote(base, safe=""))


def domain_from_url(url: str) -> str:
    return urlparse(url).netloc


def load_watchlists() -> Dict[str, List[Dict[str, str]]]:
    if not WATCHLIST_PATH.exists():
        return {}
    return json.loads(WATCHLIST_PATH.read_text())


def build_google_news_queries(
    terms: List[str],
    days: int,
    media_domains: List[str],
    term_chunk: int,
    max_queries: int,
    media_per_run: int,
    seed: int,
) -> List[Tuple[str, str]]:
    queries: List[Tuple[str, str]] = []
    # Rotate media domains daily to avoid 503s
    domains = [d for d in media_domains if d]
    if domains:
        start = seed % len(domains)
        rotated = domains[start:] + domains[:start]
        domains = rotated[:media_per_run]
    for domain in domains:
        query = f"site:{domain} (atrial fibrillation OR AFib OR LAAO OR ablation OR device OR drug) when:{days}d"
        queries.append((f"Media site {domain}", GOOGLE_NEWS_RSS_BASE.format(query=quote(query, safe=""))))

    # Fill remaining slots with tracked-term chunks
    remaining = max_queries - len(queries)
    if remaining <= 0:
        return queries

    chunk_size = max(4, term_chunk)
    chunk_count = 0
    for idx in range(0, len(terms), chunk_size):
        if chunk_count >= remaining:
            break
        chunk = terms[idx : idx + chunk_size]
        query_terms = " OR ".join(f"\"{term}\"" for term in chunk)
        query = f"({query_terms}) (atrial fibrillation OR AFib OR LAAO OR ablation OR device OR drug) when:{days}d"
        queries.append((f"Tracked terms {idx // chunk_size + 1}", GOOGLE_NEWS_RSS_BASE.format(query=quote(query, safe=""))))
        chunk_count += 1
    return queries


def parse_rss(xml_bytes: bytes) -> List[Tuple[str, str, Optional[datetime]]]:
    root = ET.fromstring(xml_bytes)
    items: List[Tuple[str, str, Optional[datetime]]] = []
    channel = root.find("channel")
    if channel is not None:
        for item in channel.findall("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            dt = parse_date_from_text(pub)
            items.append((title, link, dt))
        return items
    for entry in root.findall("{http://www.w3.org/2005/Atom}entry"):
        title = (entry.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
        link_el = entry.find("{http://www.w3.org/2005/Atom}link")
        link = link_el.attrib.get("href", "") if link_el is not None else ""
        updated = (entry.findtext("{http://www.w3.org/2005/Atom}updated") or "").strip()
        dt = parse_date_from_text(updated)
        items.append((title, link, dt))
    return items


def load_cache() -> Dict[str, Dict[str, List[Dict[str, str]]]]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text())
    except Exception:
        return {}


def save_cache(cache: Dict[str, Dict[str, List[Dict[str, str]]]]) -> None:
    CACHE_PATH.write_text(json.dumps(cache, indent=2))


def render_report(
    now: datetime,
    changes: Dict[str, List[Tuple[str, str, List[LinkItem]]]],
    totals: Dict[str, int],
) -> str:
    lines = []
    lines.append(f"# AFib CI Scan ({now.date().isoformat()})")
    lines.append("")
    lines.append(f"Run time: {now.isoformat()}")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- Press rooms updated: {totals.get('press_rooms', 0)}")
    lines.append(f"- Pipelines updated: {totals.get('pipelines', 0)}")
    lines.append(f"- Regulatory/SEC updated: {totals.get('regulatory', 0)}")
    lines.append(f"- Conferences updated: {totals.get('conferences', 0)}")
    if "google_news" in totals:
        lines.append(f"- Google News queries with updates: {totals.get('google_news', 0)}")
    lines.append("")

    all_items: List[LinkItem] = []
    for entries in changes.values():
        for _, _, items in entries:
            all_items.extend(items)

    top_items = all_items[:10]
    if top_items:
        lines.append("## Top Items")
        for item in top_items:
            lines.append(f"- {item.title} (match: {item.match})")
            lines.append(f"- {item.url}")
        lines.append("")

    grouped: Dict[str, List[LinkItem]] = {}
    for item in all_items:
        key = item.match or "Unspecified"
        grouped.setdefault(key, []).append(item)

    if grouped:
        lines.append("## By Drug/Device")
        for key in sorted(grouped.keys(), key=lambda s: s.lower()):
            lines.append(f"- {key}")
            for item in grouped[key]:
                lines.append(f"- {item.title}")
                lines.append(f"- {item.url}")
            lines.append("")

    return "\n".join(lines).strip() + "\n"


def in_conference_window(now: datetime) -> bool:
    for start_m, start_d, end_m, end_d in CONFERENCE_MODE_DATES:
        start = datetime(now.year, start_m, start_d, tzinfo=timezone.utc)
        end = datetime(now.year, end_m, end_d, tzinfo=timezone.utc)
        if start <= now <= end:
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily AFib CI scan")
    parser.add_argument("--days", type=int, default=10, help="Lookback window in days (default: 10)")
    parser.add_argument(
        "--direct-fetch",
        action="store_true",
        help="Fetch sites directly instead of using Google News RSS",
    )
    parser.add_argument(
        "--allow-keyword-only",
        action="store_true",
        help="Allow matches without tracked drug/device names",
    )
    parser.add_argument(
        "--no-conference-mode",
        action="store_true",
        help="Disable automatic conference-mode window",
    )
    parser.add_argument(
        "--verbose-errors",
        action="store_true",
        help="Print fetch errors (default: suppressed)",
    )
    parser.add_argument(
        "--strict-date",
        action="store_true",
        help="Require a parsed date in titles/URLs (filters out undated links)",
    )
    parser.add_argument(
        "--max-queries",
        type=int,
        default=6,
        help="Maximum number of Google News queries per run",
    )
    parser.add_argument(
        "--media-per-run",
        type=int,
        default=4,
        help="Number of media domains to query per run (rotated daily)",
    )
    parser.add_argument(
        "--term-chunk",
        type=int,
        default=8,
        help="Tracked-term chunk size for Google News queries",
    )
    args = parser.parse_args()

    if not WATCHLIST_PATH.exists():
        print("Missing data/ci_watchlists.json")
        return 1

    watchlists = load_watchlists()
    terms = load_terms()
    keywords = DEFAULT_KEYWORDS
    cache = load_cache()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=args.days)
    use_fallback = True
    conference_mode_active = (not args.no_conference_mode) and in_conference_window(now)
    require_tracked = not args.allow_keyword_only and not conference_mode_active

    changes: Dict[str, List[Tuple[str, str, List[LinkItem]]]] = {}
    totals: Dict[str, int] = {}

    if not args.direct_fetch:
        media_domains = watchlists.get("media_domains", [])
        queries = build_google_news_queries(
            terms,
            args.days,
            media_domains,
            args.term_chunk,
            args.max_queries,
            args.media_per_run,
            now.toordinal(),
        )
        section_changes: List[Tuple[str, str, List[LinkItem]]] = []
        for label, search_url in queries:
            try:
                xml_bytes = fetch_xml(search_url)
                items: List[LinkItem] = []
                for title, link, dt in parse_rss(xml_bytes):
                    if not title or not link:
                        continue
                    if dt is None:
                        if args.strict_date:
                            continue
                    else:
                        if dt < cutoff:
                            continue
                    hay = f"{title} {link}"
                    if has_excluded_phrase(hay):
                        continue
                    term_match = match_term(hay, terms)
                    keyword_match = match_term(hay, keywords)
                    if require_tracked and not term_match:
                        continue
                    if not term_match and not keyword_match:
                        continue
                    if not term_match and not has_include_signal(hay):
                        continue
                    items.append(LinkItem(title=title, url=link, match=term_match or keyword_match))
            except Exception as exc:  # noqa: BLE001
                if args.verbose_errors:
                    print(f"Google News fetch failed for {label}: {exc}")
                continue

            cache_entry = cache.get(search_url, {"items": []})
            prev_urls = {item.get("url") for item in cache_entry.get("items", [])}
            new_items = [item for item in items if item.url not in prev_urls]

            if new_items or (not prev_urls and items):
                section_changes.append((label, search_url, new_items))

            cache[search_url] = {
                "items": [item.__dict__ for item in items],
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }

            time.sleep(0.8)

        if section_changes:
            changes["google_news"] = section_changes
            totals["google_news"] = len(section_changes)
    else:
        for section, sources in watchlists.items():
            section_changes: List[Tuple[str, str, List[LinkItem]]] = []
            sorted_sources = sorted(sources, key=lambda s: s.get("priority", 3))
            for source in sorted_sources:
                name = (source.get("name") or "").strip()
                url = (source.get("url") or "").strip()
                if not name or not url:
                    continue
                items: List[LinkItem] = []
                try:
                    html = fetch_html(url)
                    items = extract_matches(
                        url,
                        html,
                        terms,
                        keywords,
                        cutoff,
                        args.strict_date,
                        require_tracked,
                    )
                except Exception as exc:  # noqa: BLE001
                    if args.verbose_errors:
                        print(f"Failed to fetch {name}: {exc}")
                if use_fallback:
                    try:
                        domain = domain_from_url(url)
                        search_url = google_news_query(name, args.days, domain=domain)
                        xml_url = GOOGLE_NEWS_RSS_BASE.format(query=quote(f"site:{domain} \"{name}\" (atrial fibrillation OR AFib OR LAAO OR ablation OR device OR drug) when:{args.days}d", safe=""))
                        xml_bytes = fetch_xml(xml_url)
                        filtered: List[LinkItem] = []
                        for title, link, dt in parse_rss(xml_bytes):
                            if not title or not link:
                                continue
                            if dt is None:
                                if args.strict_date:
                                    continue
                            else:
                                if dt < cutoff:
                                    continue
                            hay = f"{title} {link}"
                            if has_excluded_phrase(hay):
                                continue
                            term_match = match_term(hay, terms)
                            keyword_match = match_term(hay, keywords)
                            if require_tracked and not term_match:
                                continue
                            if not term_match and not keyword_match:
                                continue
                            if not term_match and not has_include_signal(hay):
                                continue
                            filtered.append(LinkItem(title=title, url=link, match=term_match or keyword_match))
                        items = filtered
                    except Exception as exc:  # noqa: BLE001
                        if args.verbose_errors:
                            print(f"Fallback Google News failed for {name}: {exc}")
                        continue
                else:
                    continue

                cache_entry = cache.get(url, {"items": []})
                prev_urls = {item.get("url") for item in cache_entry.get("items", [])}
                new_items = [item for item in items if item.url not in prev_urls]

                if new_items or (not prev_urls and items):
                    section_changes.append((name, url, new_items))

                cache[url] = {
                    "items": [item.__dict__ for item in items],
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }

            if section_changes:
                changes[section] = section_changes
                totals[section] = len(section_changes)

    report = render_report(now, changes, totals)
    REPORT_PATH.write_text(report)

    print(report)
    print(f"\nReport saved to {REPORT_PATH}")
    save_cache(cache)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
