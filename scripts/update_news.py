#!/usr/bin/env python3
import csv
import json
import re
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
CI_MANUAL_URLS_PATH = ROOT / "data" / "ci_manual_urls.txt"

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
        writer = csv.DictWriter(handle, fieldnames=["category", "title", "date", "source", "link"])
        writer.writeheader()
        writer.writerows(rows)


def normalize_title(title: str) -> str:
    # Drop common trailing publisher suffixes so the same story title dedupes.
    base = re.split(r"\s[-|\u2014]\s", title, maxsplit=1)[0]
    base = base.lower()
    base = re.sub(r"[^a-z0-9\s]", " ", base)
    base = re.sub(r"\s+", " ", base).strip()
    return base


def source_priority(source: str) -> int:
    value = source.lower()
    if "fda" in value or "ema" in value:
        return 1
    if "mediaroom" in value or "press" in value:
        return 2
    if "google news" in value:
        return 4
    return 3


def dedupe_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    # Deduplicate within each category by normalized title + date.
    best = {}
    for row in rows:
        title = (row.get("title") or "").strip()
        if not title:
            continue
        key = (
            (row.get("category") or "").strip(),
            normalize_title(title),
            (row.get("date") or "").strip(),
        )
        current = best.get(key)
        if current is None:
            best[key] = row
            continue
        score_new = source_priority(row.get("source", ""))
        score_old = source_priority(current.get("source", ""))
        # Prefer higher-trust source and longer title detail when tied.
        if score_new < score_old or (
            score_new == score_old and len(row.get("title", "")) > len(current.get("title", ""))
        ):
            best[key] = row
    return list(best.values())


def keep_row(row: Dict[str, str]) -> bool:
    source = (row.get("source") or "").lower()
    link = (row.get("link") or "").lower()
    title = (row.get("title") or "")
    nct_id = extract_nct_id(f"{title} {link}")
    # Drop older broad CI-manual imports; retain only ClinicalTrials.gov tracked links.
    if "ci manual scan" in source and "clinicaltrials.gov/study/" not in link:
        return False
    # Drop legacy CI-manual trial rows without dates; new rows are date-stamped.
    if "ci manual scan" in source and "clinicaltrials.gov/study/" in link and not (row.get("date") or "").strip():
        return False
    # Keep canonical CI-manual trial title format that includes NCT id.
    if (
        "ci manual scan" in source
        and "clinicaltrials.gov/study/" in link
        and nct_id
        and nct_id not in title.upper()
    ):
        return False
    return True


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


def load_registry_ids() -> Dict[str, List[str]]:
    if not AFIB_PATH.exists():
        return {}
    data = json.loads(AFIB_PATH.read_text())
    out: Dict[str, List[str]] = {}
    for item in data.get("items", []):
        name = (item.get("name") or "").strip()
        company = (item.get("company") or "").strip()
        label = name or company
        for trial in item.get("trials", []):
            rid = (trial.get("registry_id") or "").strip().upper()
            if not rid.startswith("NCT"):
                continue
            values = out.setdefault(rid, [])
            if label and label not in values:
                values.append(label)
    return out


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


def is_af_relevant(title: str, link: str) -> bool:
    haystack = f"{title} {link}".lower()

    include_terms = [
        "atrial fibrillation",
        "afib",
        "atrial flutter",
        "left atrial appendage",
        "laao",
        "laac",
        "pfa",
        "pulsed field ablation",
        "catheter ablation",
        "pulmonary vein",
        "watchman",
        "amulet",
        "rhythm control",
        "rate control",
        "stroke prevention",
        "anticoagul",
        "arrhythm",
    ]
    if not any(term in haystack for term in include_terms):
        return False

    # Hard-exclude high-frequency false positives.
    exclude_terms = [
        "governor abbott",
        "greg abbott",
        "tony abbott",
        "abbott elementary",
        "texas workforce commission",
    ]
    if any(term in haystack for term in exclude_terms):
        return False
    return True


def parse_manual_input_line(line: str) -> Optional[Tuple[str, str]]:
    text_line = line.strip()
    if not text_line or text_line.startswith("#"):
        return None
    if "\t" in text_line:
        left, right = text_line.split("\t", 1)
        title = left.strip()
        link = right.strip()
        if link.startswith("http"):
            return title, link
    if text_line.startswith("http"):
        return "", text_line
    return None


def extract_nct_id(text_value: str) -> str:
    m = re.search(r"\bNCT\d{8}\b", (text_value or "").upper())
    return m.group(0) if m else ""


def manual_ci_rows(
    terms: List[str],
    seen: set,
    registry_map: Dict[str, List[str]],
) -> List[Dict[str, str]]:
    if not CI_MANUAL_URLS_PATH.exists():
        return []
    rows: List[Dict[str, str]] = []
    today = datetime.now(timezone.utc).date().isoformat()
    for raw in CI_MANUAL_URLS_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
        parsed = parse_manual_input_line(raw)
        if not parsed:
            continue
        title, link = parsed
        if not link:
            continue
        nct_id = extract_nct_id(f"{title} {link}")
        has_ctgov_trial = "clinicaltrials.gov/study/" in link.lower() and bool(nct_id)
        # Keep CI-manual ingestion narrowly focused on tracked ClinicalTrials.gov items.
        if not has_ctgov_trial:
            continue
        if not title:
            title = nct_id or link
        if nct_id and f"({nct_id})" not in title:
            title = f"{title} ({nct_id})"

        if not is_af_relevant(title, link):
            # Let tracked ClinicalTrials.gov trial pages through even if title text is sparse.
            if not (has_ctgov_trial and nct_id in registry_map):
                continue

        match = find_match(title, terms)
        if not match and has_ctgov_trial and nct_id in registry_map:
            match = registry_map[nct_id][0]
        if not match:
            continue

        row = {
            "category": "press_pipeline",
            "title": title,
            "date": today,
            "source": f"CI manual scan · Match: {match}",
            "link": link,
        }
        key = (row["category"], normalize_title(row["title"]), row["date"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return rows


def main() -> int:
    if not SOURCES_PATH.exists():
        print("Missing data/news_sources.json")
        return 1

    terms = load_terms()
    registry_map = load_registry_ids()
    sources = json.loads(SOURCES_PATH.read_text())
    sources += build_google_news_sources(terms)
    sources += load_company_press_sources()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=7)

    existing = [
        row
        for row in read_existing()
        if is_af_relevant(row.get("title", ""), row.get("link", "")) and keep_row(row)
    ]
    existing = dedupe_rows(existing)
    seen = set(
        (
            row.get("category", ""),
            normalize_title(row.get("title", "")),
            row.get("date", ""),
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
            if not is_af_relevant(title, link):
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
                "link": link,
            }
            key = (row["category"], normalize_title(row["title"]), row["date"])
            if key in seen:
                continue
            seen.add(key)
            new_rows.append(row)

    new_rows.extend(manual_ci_rows(terms=terms, seen=seen, registry_map=registry_map))

    combined = dedupe_rows(existing + new_rows)
    write_rows(combined)
    print(f"Added {len(new_rows)} new weekly updates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
