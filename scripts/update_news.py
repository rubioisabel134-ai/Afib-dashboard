#!/usr/bin/env python3
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.request import Request, urlopen
import urllib.parse
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "weekly_updates.csv"
SOURCES_PATH = ROOT / "data" / "news_sources.json"
AFIB_PATH = ROOT / "data" / "afib.json"
COMPANY_PRESS_PATH = ROOT / "data" / "company_press.json"

CATEGORIES = {
    "safety_signals",
    "label_expansions",
    "guideline_updates",
    "conference_abstracts",
    "press_pipeline",
}

GOOGLE_NEWS_BASE = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"


def fetch_xml(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": "AFib-Dashboard-News/1.0"})
    with urlopen(req, timeout=20) as resp:
        return resp.read()


def parse_date(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    raw = raw.strip()
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def text(el: Optional[ET.Element]) -> str:
    return (el.text or "").strip() if el is not None else ""


def parse_rss(xml_bytes: bytes) -> List[Tuple[str, str, Optional[datetime]]]:
    root = ET.fromstring(xml_bytes)
    items = []

    # RSS 2.0
    channel = root.find("channel")
    if channel is not None:
        for item in channel.findall("item"):
            title = text(item.find("title"))
            link = text(item.find("link"))
            pub = text(item.find("pubDate")) or text(item.find("dc:date"))
            dt = parse_date(pub)
            items.append((title, link, dt))
        return items

    # Atom
    for entry in root.findall("{http://www.w3.org/2005/Atom}entry"):
        title = text(entry.find("{http://www.w3.org/2005/Atom}title"))
        link_el = entry.find("{http://www.w3.org/2005/Atom}link")
        link = link_el.attrib.get("href", "") if link_el is not None else ""
        updated = text(entry.find("{http://www.w3.org/2005/Atom}updated"))
        published = text(entry.find("{http://www.w3.org/2005/Atom}published"))
        dt = parse_date(updated or published)
        items.append((title, link, dt))

    return items


def read_existing() -> List[Dict[str, str]]:
    if not CSV_PATH.exists():
        return []
    with CSV_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [row for row in reader]


def write_rows(rows: List[Dict[str, str]]) -> None:
    with CSV_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["category", "title", "date", "source"])
        writer.writeheader()
        writer.writerows(rows)


def load_terms() -> List[str]:
    if not AFIB_PATH.exists():
        return []
    data = json.loads(AFIB_PATH.read_text())
    terms = []
    for item in data.get("items", []):
        name = (item.get("name") or "").strip()
        company = (item.get("company") or "").strip()
        if name:
            terms.append(name)
        if company:
            terms.append(company)
    # De-duplicate while preserving order
    seen = set()
    cleaned = []
    for term in terms:
        term = term.replace("(", "").replace(")", "").replace("\"", "").strip()
        if not term or term in seen:
            continue
        seen.add(term)
        cleaned.append(term)
    return cleaned


def build_google_news_sources(terms: List[str]) -> List[Dict[str, str]]:
    if not terms:
        return []
    sources = []
    chunk_size = 12
    for idx in range(0, len(terms), chunk_size):
        chunk = terms[idx : idx + chunk_size]
        query_terms = " OR ".join(f'\"{term}\"' for term in chunk)
        query = f"({query_terms}) (atrial fibrillation OR AFib) when:7d"
        safe_query = urllib.parse.quote(query, safe="")
        sources.append(
            {
                "name": f"Google News: AFib watchlist {idx // chunk_size + 1}",
                "category": "press_pipeline",
                "url": GOOGLE_NEWS_BASE.format(query=safe_query),
                "require_match": True,
            }
        )
    return sources


def load_company_press_sources() -> List[Dict[str, str]]:
    if not COMPANY_PRESS_PATH.exists():
        return []
    try:
        data = json.loads(COMPANY_PRESS_PATH.read_text())
    except Exception:
        return []
    sources = []
    for entry in data:
        name = (entry.get("name") or "").strip()
        url = (entry.get("url") or "").strip()
        if not name or not url:
            continue
        sources.append(
            {
                "name": name,
                "category": "press_pipeline",
                "url": url,
            }
        )
    return sources


def find_match(title: str, terms: List[str]) -> str:
    title_lower = title.lower()
    for term in terms:
        if term.lower() in title_lower:
            return term
    return ""


def main() -> int:
    if not SOURCES_PATH.exists():
        print("Missing data/news_sources.json")
        return 1

    terms = load_terms()
    sources = json.loads(SOURCES_PATH.read_text())
    sources += build_google_news_sources(terms)
    sources += load_company_press_sources()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=7)

    existing = read_existing()
    seen = set(
        (
            row.get("category", ""),
            row.get("title", ""),
            row.get("date", ""),
            row.get("source", ""),
        )
        for row in existing
    )

    new_rows: List[Dict[str, str]] = []

    for source in sources:
        category = source.get("category")
        url = source.get("url")
        name = source.get("name")
        require_match = source.get("require_match", True)
        if category not in CATEGORIES or not url or not name:
            continue

        try:
            xml_bytes = fetch_xml(url)
            items = parse_rss(xml_bytes)
        except Exception as exc:  # noqa: BLE001
            print(f"Failed to fetch {name}: {exc}")
            continue

        for title, link, dt in items:
            if not title:
                continue
            if dt and dt < cutoff:
                continue
            date_str = dt.date().isoformat() if dt else ""
            match = find_match(title, terms)
            if require_match and not match:
                continue
            source_label = name if not match else f"{name} · Match: {match}"
            row = {
                "category": category,
                "title": title,
                "date": date_str,
                "source": source_label,
            }
            key = (row["category"], row["title"], row["date"], row["source"])
            if key in seen:
                continue
            seen.add(key)
            new_rows.append(row)

    combined = existing + new_rows
    write_rows(combined)
    print(f"Added {len(new_rows)} new weekly updates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
