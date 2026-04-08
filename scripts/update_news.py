#!/usr/bin/env python3
import argparse
import csv
import html
import json
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
import urllib.parse
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "weekly_updates.csv"
SOURCES_PATH = ROOT / "data" / "news_sources.json"
AFIB_PATH = ROOT / "data" / "afib.json"
COMPANY_PRESS_PATH = ROOT / "data" / "company_press.json"
CONFERENCE_SOURCES_PATH = ROOT / "data" / "conference_sources.json"
CONFERENCE_CALENDAR_PATH = ROOT / "data" / "conference_calendar.json"
CI_MANUAL_URLS_PATH = ROOT / "data" / "ci_manual_urls.txt"
ARTICLE_CACHE_PATH = ROOT / "data" / "company_press_cache.json"

CATEGORIES = {
    "safety_signals",
    "label_expansions",
    "guideline_updates",
    "conference_abstracts",
    "press_pipeline",
}

GOOGLE_NEWS_BASE = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

AF_RELEVANT_TERMS = [
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
    "factor xi",
    "fxi",
]

AF_EXCLUDE_TERMS = [
    "governor abbott",
    "greg abbott",
    "tony abbott",
    "abbott elementary",
    "texas workforce commission",
    "obituary",
    "funeral home",
    "memorial",
    "died",
    "stock price",
    "insider buy",
    "marketbeat",
    "yahoo finance",
    "stake in abbott laboratories",
    "wealth llc",
    "investor alert",
    "earnings call",
    "record month in dollars",
    "weight-loss news",
    "semaglutide",
    "deep pipeline",
    "dividend",
    "shares",
    "stock rises",
    "stock price today",
    "venous thromboembolism",
    " vte ",
    "total knee arthroplasty",
    " knee arthroplasty",
    "hyperlipoproteinemia",
    "lipoprotein(a)",
    "lipoprotein a",
    "chronic coronary",
    "peripheral arterial disease",
    "peripheral artery disease",
]

DEVELOPMENT_SIGNAL_TERMS = [
    "trial",
    "study",
    "phase",
    "pivotal",
    "registrational",
    "topline",
    "enrollment",
    "pipeline",
    "investigational",
    "candidate",
    "program",
    "approval",
    "approved",
    "authorization",
    "fda",
    "ema",
    "nmpa",
    "pmda",
    "device",
    "drug",
    "catheter",
    "ablation",
    "late-breaking",
    "oral presentation",
    "simultaneous publication",
    "presentation",
    "abstract",
    "congress",
    "scientific sessions",
]

CONFERENCE_SIGNAL_TERMS = [
    "acc.26",
    "acc 2026",
    "american college of cardiology",
    "scientific session",
    "late-breaking",
    "late breaker",
    "oral presentation",
    "oral abstract",
    "breaking clinical trial",
    "simultaneous publication",
    "presented at",
    "presented during",
    "conference presentation",
    "abstract",
    "heart rhythm 2026",
    "heart rhythm society",
    "hrs 2026",
    "ehra 2026",
    "ehra congress",
    "esc congress 2026",
    "esc congress",
    "aha scientific sessions",
    "scientific sessions 2026",
    "aha 2026",
]

GENERIC_CANDIDATE_TOKENS = {
    "AFIB",
    "COVID",
    "RNA",
    "DNA",
    "EMA",
    "FDA",
    "NMPA",
    "PMDA",
    "PFA",
    "LAAO",
    "LAAC",
    "FXI",
}


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
        text_value = data.strip()
        if text_value:
            self._text_parts.append(text_value)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        text_value = " ".join(self._text_parts).strip()
        self.links.append((text_value, self._href))
        self._href = None
        self._text_parts = []


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: List[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text_value = data.strip()
        if text_value:
            self.parts.append(text_value)


class ListingLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.entries: List[Dict[str, str]] = []
        self._parts: List[str] = []
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
        self._href = href
        self._text_parts = []

    def handle_data(self, data: str) -> None:
        text_value = data.strip()
        if not text_value:
            return
        self._parts.append(text_value)
        if self._href is not None:
            self._text_parts.append(text_value)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        anchor_text = " ".join(self._text_parts).strip()
        context_text = " ".join(self._parts[-8:]).strip()
        self.entries.append(
            {
                "href": self._href,
                "text": anchor_text,
                "context": context_text,
            }
        )
        self._href = None
        self._text_parts = []


def fetch_xml(url: str) -> bytes:
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AFib-Dashboard-News/1.0",
            "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.9, */*;q=0.5",
        },
    )
    # Retry transient upstream throttling / gateway failures.
    for attempt in range(3):
        try:
            with urlopen(req, timeout=20) as resp:
                return resp.read()
        except HTTPError as exc:
            if exc.code in {429, 500, 502, 503, 504} and attempt < 2:
                time.sleep(1.2 * (attempt + 1))
                continue
            raise
        except URLError:
            if attempt < 2:
                time.sleep(1.2 * (attempt + 1))
                continue
            raise


def fetch_html(url: str) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AFib-Dashboard-News/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.8",
        },
    )
    for attempt in range(3):
        try:
            with urlopen(req, timeout=20) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except HTTPError as exc:
            if exc.code in {429, 500, 502, 503, 504} and attempt < 2:
                time.sleep(1.2 * (attempt + 1))
                continue
            raise
        except URLError:
            if attempt < 2:
                time.sleep(1.2 * (attempt + 1))
                continue
            raise


def fetch_ctgov_last_update_date(nct_id: str) -> str:
    nct = (nct_id or "").upper().strip()
    if not nct.startswith("NCT"):
        return ""
    url = f"https://clinicaltrials.gov/api/v2/studies/{nct}"
    try:
        req = Request(url, headers={"User-Agent": "AFib-Dashboard-News/1.0"})
        with urlopen(req, timeout=20) as resp:
            payload = json.load(resp)
    except Exception:
        return ""

    status = payload.get("protocolSection", {}).get("statusModule", {})
    candidates = [
        status.get("lastUpdatePostDateStruct", {}).get("date"),
        status.get("primaryCompletionDateStruct", {}).get("date"),
        status.get("completionDateStruct", {}).get("date"),
    ]
    for raw in candidates:
        dt = parse_date(raw)
        if dt:
            return dt.date().isoformat()
    return ""


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


def normalize_url(base_url: str, link: str) -> Optional[str]:
    raw = (link or "").strip()
    if not raw or raw.startswith(("javascript:", "mailto:", "#")):
        return None
    absolute = urljoin(base_url, raw)
    parsed = urlparse(absolute)
    if not parsed.scheme.startswith("http"):
        return None
    return absolute


def page_title_from_html(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def extract_visible_text(html: str) -> str:
    parser = VisibleTextParser()
    parser.feed(html)
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def parse_html_date(html: str, url: str = "", fallback_text: str = "") -> Optional[datetime]:
    patterns = [
        r'article:published_time"\s*content="([^"]+)"',
        r'article:modified_time"\s*content="([^"]+)"',
        r'property="og:updated_time"\s*content="([^"]+)"',
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'"dateModified"\s*:\s*"([^"]+)"',
        r'<time[^>]*datetime="([^"]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if not match:
            continue
        parsed = parse_date(match.group(1))
        if parsed:
            return parsed
    return parse_date_from_text(f"{url} {fallback_text}")


def parse_date_candidates(text_value: str) -> List[datetime]:
    haystack = text_value or ""
    haystack = re.sub(r"<[^>]+>", " ", haystack)
    haystack = re.sub(r"\^\{(st|nd|rd|th)\}", r"\1", haystack, flags=re.IGNORECASE)
    haystack = re.sub(r"\s+", " ", haystack)
    out: List[datetime] = []

    for year, month, day in re.findall(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", haystack):
        try:
            out.append(datetime(int(year), int(month), int(day), tzinfo=timezone.utc))
        except ValueError:
            continue

    month_names = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    for month_token, day_token, year_token in re.findall(
        r"\b("
        r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
        r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
        r")\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})\b",
        haystack,
        flags=re.IGNORECASE,
    ):
        month = month_names.get(month_token.lower())
        if not month:
            continue
        try:
            out.append(datetime(int(year_token), month, int(day_token), tzinfo=timezone.utc))
        except ValueError:
            continue

    return out


def infer_listing_date(listing_html: str, article_url: str, link_text: str = "") -> Optional[datetime]:
    needles = []
    parsed = urlparse(article_url)
    if parsed.path:
        needles.append(parsed.path)
    needles.append(article_url)
    if link_text:
        needles.append(link_text[:80])

    for needle in needles:
        if not needle:
            continue
        idx = listing_html.find(needle)
        if idx < 0:
            continue
        start = max(0, idx - 500)
        end = min(len(listing_html), idx + 250)
        window = listing_html[start:end]
        candidates = parse_date_candidates(window)
        if candidates:
            return candidates[-1]
    return None


def load_article_cache() -> Dict[str, Dict[str, str]]:
    if not ARTICLE_CACHE_PATH.exists():
        return {}
    try:
        data = json.loads(ARTICLE_CACHE_PATH.read_text())
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out: Dict[str, Dict[str, str]] = {}
    for url, payload in data.items():
        if isinstance(url, str) and isinstance(payload, dict):
            out[url] = {str(key): str(value) for key, value in payload.items()}
    return out


def save_article_cache(cache: Dict[str, Dict[str, str]]) -> None:
    ARTICLE_CACHE_PATH.write_text(json.dumps(cache, indent=2))


def get_article_details(
    article_url: str,
    link_text: str,
    listing_date: str,
    article_cache: Dict[str, Dict[str, str]],
) -> Optional[Dict[str, str]]:
    cached = article_cache.get(article_url)
    if cached:
        return cached

    try:
        article_html = fetch_html(article_url)
    except Exception:
        return None

    title = page_title_from_html(article_html) or link_text or article_url
    body_text = extract_visible_text(article_html)
    dt = parse_html_date(article_html, url=article_url, fallback_text=f"{title} {link_text}")
    if dt is None and listing_date:
        dt = parse_date(listing_date)

    payload = {
        "title": title,
        "body_text": body_text,
        "page_date": dt.date().isoformat() if dt else "",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    article_cache[article_url] = payload
    return payload


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


def is_regulatory_item(title: str, link: str, source: str = "") -> bool:
    text_blob = f"{title} {link} {source}".lower()
    terms = [
        "expanded approval",
        "approval",
        "approved",
        "fda approval",
        "fda approved",
        "approved by fda",
        "pma approval",
        "510(k)",
        "ce mark",
        "ce-mark",
        "ema approval",
        "marketing authorization",
        "nmpa",
        "pmda",
        "approved in china",
        "approval in china",
        "approved in japan",
        "approval in japan",
        "regulatory approval",
        "clearance",
        "patent",
        "granted patent",
        "breakthrough device designation",
    ]
    return any(term in text_blob for term in terms)


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
    def term_variants(text_value: str, *, is_company: bool = False) -> List[str]:
        raw = (text_value or "").strip()
        if not raw:
            return []
        variants = [raw]
        if not is_company:
            alias = re.sub(
                r"\b(platform|system|device|program|therapy|therapeutic|catheter|portfolio)\b",
                "",
                raw,
                flags=re.IGNORECASE,
            )
            alias = re.sub(r"\s+", " ", alias).strip(" -/")
            if alias and alias not in variants:
                variants.append(alias)
            head = alias.split()[0] if alias else ""
            if head and len(head) >= 5 and any(ch.isupper() for ch in head):
                variants.append(head)
        if is_company:
            for token in re.split(r"[/,;]|(?:\s+\&\s+)", raw):
                token = token.strip()
                if len(token) >= 6 and len(token.split()) >= 2:
                    variants.append(token)
        return variants

    if not AFIB_PATH.exists():
        return []
    data = json.loads(AFIB_PATH.read_text())
    terms = []
    for item in data.get("items", []):
        name = (item.get("name") or "").strip()
        company = (item.get("company") or "").strip()
        terms.extend(term_variants(name, is_company=False))
        terms.extend(term_variants(company, is_company=True))
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


def parse_date_from_text(text_value: str) -> Optional[datetime]:
    haystack = text_value or ""
    iso_match = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", haystack)
    if iso_match:
        year, month, day = map(int, iso_match.groups())
        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            return None

    us_match = re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](20\d{2})\b", haystack)
    if us_match:
        month, day, year = map(int, us_match.groups())
        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            return None

    month_names = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    month_first = re.search(
        r"\b("
        r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
        r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
        r")\s+(\d{1,2}),?\s+(20\d{2})\b",
        haystack,
        flags=re.IGNORECASE,
    )
    if month_first:
        month_token, day_token, year_token = month_first.groups()
        month = month_names.get(month_token.lower())
        if month:
            try:
                return datetime(int(year_token), month, int(day_token), tzinfo=timezone.utc)
            except ValueError:
                return None

    day_first = re.search(
        r"\b(\d{1,2})\s+("
        r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
        r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
        r"),?\s+(20\d{2})\b",
        haystack,
        flags=re.IGNORECASE,
    )
    if day_first:
        day_token, month_token, year_token = day_first.groups()
        month = month_names.get(month_token.lower())
        if month:
            try:
                return datetime(int(year_token), month, int(day_token), tzinfo=timezone.utc)
            except ValueError:
                return None

    return None


def build_google_news_sources(terms: List[str]) -> List[Dict[str, str]]:
    if not terms:
        return []
    sources = []
    # Larger chunks reduce request count and lower 503 throttling risk.
    chunk_size = 28
    for idx in range(0, len(terms), chunk_size):
        chunk = terms[idx : idx + chunk_size]
        query_terms = " OR ".join(f'\"{term}\"' for term in chunk)
        query = (
            f"({query_terms}) (atrial fibrillation OR AFib) "
            f"(\"press release\" OR trial OR phase OR study OR topline OR enrollment) when:7d"
        )
        safe_query = urllib.parse.quote(query, safe="")
        sources.append(
            {
                "name": f"Google News: AFib watchlist {idx // chunk_size + 1}",
                "category": "press_pipeline",
                "source_type": "google_news_query",
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
        query = (entry.get("query") or "").strip()
        source_type = (entry.get("source_type") or "").strip()
        require_match = entry.get("require_match", True)
        if not name or (not url and not query):
            continue
        if query:
            safe_query = urllib.parse.quote(query, safe="")
            sources.append(
                {
                    "name": name,
                    "category": "press_pipeline",
                    "source_type": source_type or "google_news_query",
                    "url": GOOGLE_NEWS_BASE.format(query=safe_query),
                    "require_match": require_match,
                }
            )
            continue
        sources.append(
            {
                "name": name,
                "category": "press_pipeline",
                "source_type": source_type or "rss",
                "url": url,
                "require_match": require_match,
                "crawl_limit": int(entry.get("crawl_limit", 12)),
            }
        )
    return sources


def parse_iso_date(raw: str) -> Optional[datetime]:
    text_value = (raw or "").strip()
    if not text_value:
        return None
    try:
        return datetime.fromisoformat(text_value).replace(tzinfo=timezone.utc)
    except Exception:
        return None


def load_conference_windows() -> Dict[str, Tuple[datetime, datetime]]:
    if not CONFERENCE_CALENDAR_PATH.exists():
        return {}
    try:
        data = json.loads(CONFERENCE_CALENDAR_PATH.read_text())
    except Exception:
        return {}

    windows: Dict[str, Tuple[datetime, datetime]] = {}
    for entry in data:
        conference = (entry.get("conference") or "").strip().upper()
        start_dt = parse_iso_date(entry.get("start_date", ""))
        end_dt = parse_iso_date(entry.get("end_date", ""))
        if not conference or start_dt is None or end_dt is None:
            continue
        windows[conference] = (start_dt, end_dt)
    return windows


def load_conference_sources(now: datetime) -> List[Dict[str, str]]:
    if not CONFERENCE_SOURCES_PATH.exists():
        return []
    try:
        data = json.loads(CONFERENCE_SOURCES_PATH.read_text())
    except Exception:
        return []

    windows = load_conference_windows()
    out: List[Dict[str, str]] = []
    for entry in data:
        name = (entry.get("name") or "").strip()
        url = (entry.get("url") or "").strip()
        conference = (entry.get("conference") or "").strip().upper()
        if not name or not url or not conference:
            continue
        source = {
            "name": name,
            "category": (entry.get("category") or "conference_abstracts").strip(),
            "source_type": (entry.get("source_type") or "html_listing").strip(),
            "url": url,
            "require_match": entry.get("require_match", True),
            "crawl_limit": int(entry.get("crawl_limit", 6)),
            "lookback_days": int(entry.get("lookback_days", 21)),
            "conference": conference,
            "priority": int(entry.get("priority", 3)),
        }
        window = windows.get(conference)
        if window is not None:
            start_dt, end_dt = window
            if start_dt - timedelta(days=14) <= now <= end_dt + timedelta(days=7):
                source["active_window"] = "1"
        out.append(source)

    out.sort(
        key=lambda source: (
            source.get("conference", ""),
            0 if source.get("active_window") else 1,
            int(source.get("priority", 3)),
            source.get("name", ""),
        )
    )
    return out


def find_match(text_value: str, terms: List[str]) -> str:
    title_lower = html.unescape(text_value).lower()
    for term in terms:
        if term.lower() in title_lower:
            return term
    return ""


def is_af_relevant(title: str, link: str, body_text: str = "") -> bool:
    haystack = f"{title} {link} {body_text}".lower()
    if not any(term in haystack for term in AF_RELEVANT_TERMS):
        return False

    if any(term in haystack for term in AF_EXCLUDE_TERMS):
        return False
    return True


def has_conference_signal(
    title: str,
    link: str,
    body_text: str = "",
    source_name: str = "",
    conference: str = "",
) -> bool:
    haystack = f"{title} {link} {body_text} {source_name} {conference}".lower()
    if any(term in haystack for term in CONFERENCE_SIGNAL_TERMS):
        return True
    conference_lower = (conference or "").strip().lower()
    return bool(conference_lower and conference_lower in haystack)


def has_development_signal(text_value: str) -> bool:
    lower = text_value.lower()
    return any(term in lower for term in DEVELOPMENT_SIGNAL_TERMS)


def find_new_candidate(text_value: str, terms: List[str]) -> str:
    known = {term.lower() for term in terms}
    for pattern in (r"\b[A-Z]{2,6}-\d{2,6}[A-Z]?\b", r"\b[A-Z]{3,8}\d{2,6}[A-Z]?\b"):
        for match in re.finditer(pattern, text_value):
            token = match.group(0).strip()
            if token in GENERIC_CANDIDATE_TOKENS:
                continue
            if token.lower() in known:
                continue
            return token
    return ""


def is_company_like_term(term: str) -> bool:
    lower = term.lower()
    company_markers = [
        " therapeutics",
        " pharma",
        " pharmaceuticals",
        " medical",
        " scientific",
        " biosciences",
        " biologics",
        " health",
        " healthcare",
        " labs",
        " laboratories",
        " biotech",
        " medtech",
    ]
    return any(marker in lower for marker in company_markers) or "/" in lower or "&" in lower


def analyze_match(title: str, link: str, terms: List[str], body_text: str = "") -> Tuple[str, str]:
    headline = f"{title} {link}"
    full_text = f"{headline} {body_text}"
    overall_af = is_af_relevant(title, link, body_text)
    headline_af = is_af_relevant(title, link)
    headline_new = find_new_candidate(headline, terms)
    if headline_new and overall_af and has_development_signal(full_text):
        return "", headline_new
    headline_match = find_match(headline, terms)
    headline_specific_match = ""
    if headline_match and not is_company_like_term(headline_match):
        headline_specific_match = headline_match
    if headline_specific_match and overall_af:
        return headline_specific_match, ""
    if headline_match and headline_af:
        return headline_match, ""
    tracked_match = find_match(full_text, terms)
    if tracked_match and is_company_like_term(tracked_match):
        if headline_af:
            return tracked_match, ""
        return "", ""
    if tracked_match:
        if overall_af and (headline_af or headline_specific_match or headline_new):
            return tracked_match, ""
        return "", ""
    if not overall_af:
        return "", ""
    if not has_development_signal(full_text):
        return "", ""
    return "", find_new_candidate(full_text, terms)


def category_requires_conference_signal(category: str) -> bool:
    return (category or "").strip().lower() == "conference_abstracts"


def is_source_relevant(
    category: str,
    title: str,
    link: str,
    body_text: str = "",
    source_name: str = "",
    conference: str = "",
) -> bool:
    if not is_af_relevant(title, link, body_text):
        return False
    if category_requires_conference_signal(category):
        return has_conference_signal(
            title,
            link,
            body_text,
            source_name=source_name,
            conference=conference,
        )
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
    ctgov_date_cache: Dict[str, str] = {}
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
            "date": "",
            "source": f"CI manual scan · Match: {match}",
            "link": link,
        }
        if nct_id:
            if nct_id not in ctgov_date_cache:
                ctgov_date_cache[nct_id] = fetch_ctgov_last_update_date(nct_id)
            row["date"] = ctgov_date_cache[nct_id]
        key = (row["category"], normalize_title(row["title"]), row["date"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return rows


def should_crawl_press_link(
    listing_url: str,
    article_url: str,
    link_text: str,
    source_type: str = "html_press_room",
) -> bool:
    listing = urlparse(listing_url)
    article = urlparse(article_url)
    if listing.netloc != article.netloc:
        return False
    if article_url.rstrip("/") == listing_url.rstrip("/"):
        return False
    article_path = article.path.lower()
    listing_path = listing.path.lower().rstrip("/")
    if article_path == listing_path:
        return False
    if article_path in {"", "/"}:
        return False
    if re.search(r"/index\d*\.html?$", article_path):
        return False
    if source_type == "html_listing":
        if re.search(r"/(article|articles|news|story|stories|meetings|features|conference|congress|session|sessions)/", article_path):
            return True
        if re.search(r"/\d{4}/\d{2}/", article_path):
            return True
    hints = [
        "/news/",
        "/press",
        "/press-release",
        "/releases/",
        "/media/",
        "/companynews/",
        "/html/companynews/",
    ]
    haystack = f"{article_url} {link_text}".lower()
    if any(hint in haystack for hint in hints):
        return True
    if re.search(r"/\d{2,}\.html?$", article_path):
        return True
    return False


def listing_is_candidate(
    text_value: str,
    terms: List[str],
    category: str = "press_pipeline",
    source_name: str = "",
    conference: str = "",
) -> bool:
    tracked_match, new_candidate = analyze_match(text_value, "", terms)
    if tracked_match or new_candidate:
        if category_requires_conference_signal(category):
            return has_conference_signal(
                text_value,
                "",
                text_value,
                source_name=source_name,
                conference=conference,
            )
        return True
    return is_source_relevant(
        category,
        text_value,
        "",
        text_value,
        source_name=source_name,
        conference=conference,
    )


def extract_press_room_links(
    listing_url: str,
    html: str,
    terms: List[str],
    cutoff: datetime,
    category: str = "press_pipeline",
    source_name: str = "",
    conference: str = "",
    source_type: str = "html_press_room",
) -> List[Dict[str, str]]:
    parser = ListingLinkParser()
    parser.feed(html)
    seen: Set[str] = set()
    out: List[Dict[str, str]] = []
    for entry in parser.entries:
        link_text = re.sub(r"\s+", " ", entry.get("text", "")).strip()
        href = entry.get("href", "")
        article_url = normalize_url(listing_url, href)
        if not article_url:
            continue
        context_text = re.sub(r"\s+", " ", entry.get("context", "")).strip()
        text_value = link_text or context_text or article_url
        if not should_crawl_press_link(listing_url, article_url, text_value, source_type=source_type):
            continue
        if article_url in seen:
            continue
        listing_date = infer_listing_date(html, article_url, link_text=link_text)
        if listing_date and listing_date < cutoff:
            continue
        if not listing_is_candidate(
            f"{link_text} {context_text} {article_url}",
            terms,
            category=category,
            source_name=source_name,
            conference=conference,
        ):
            continue
        seen.add(article_url)
        out.append(
            {
                "url": article_url,
                "text": link_text,
                "context": context_text,
                "date": listing_date.date().isoformat() if listing_date else "",
            }
        )
    return out


def fetch_html_press_items(
    source: Dict[str, str],
    cutoff: datetime,
    terms: List[str],
    article_cache: Dict[str, Dict[str, str]],
) -> List[Dict[str, str]]:
    listing_url = source["url"]
    listing_html = fetch_html(listing_url)
    crawl_limit = int(source.get("crawl_limit", 4))
    require_match = source.get("require_match", True)
    category = source.get("category", "press_pipeline")
    source_name = source.get("name", "")
    conference = source.get("conference", "")
    items: List[Dict[str, str]] = []

    for entry in extract_press_room_links(
        listing_url,
        listing_html,
        terms,
        cutoff,
        category=category,
        source_name=source_name,
        conference=conference,
        source_type=(source.get("source_type") or "html_press_room"),
    )[:crawl_limit]:
        link_text = entry.get("text", "")
        article_url = entry.get("url", "")
        listing_date = (entry.get("date") or "").strip()
        article = get_article_details(
            article_url=article_url,
            link_text=link_text,
            listing_date=listing_date,
            article_cache=article_cache,
        )
        if article is None:
            continue
        title = article.get("title", "") or link_text or article_url
        body_text = article.get("body_text", "")
        if normalize_url(listing_url, article_url) == listing_url.rstrip("/") or title.strip().lower() in {
            "news",
            "atricure news",
            "press releases",
        }:
            continue
        dt = parse_date(article.get("page_date", ""))
        if dt is None:
            dt = infer_listing_date(listing_html, article_url, link_text=link_text)
        if dt and dt < cutoff:
            continue
        if not is_source_relevant(
            category,
            title,
            article_url,
            body_text,
            source_name=source_name,
            conference=conference,
        ):
            continue
        tracked_match, new_candidate = analyze_match(title, article_url, terms, body_text)
        if require_match and not tracked_match and not new_candidate:
            continue
        match_label = tracked_match or (f"NEW: {new_candidate}" if new_candidate else "")
        items.append(
            {
                "title": title,
                "link": article_url,
                "date": dt.date().isoformat() if dt else "",
                "match": match_label,
            }
        )
    return items


def fetch_source_items(
    source: Dict[str, str],
    cutoff: datetime,
    terms: List[str],
    article_cache: Dict[str, Dict[str, str]],
) -> List[Dict[str, str]]:
    source_type = (source.get("source_type") or "rss").strip().lower()
    category = source.get("category", "press_pipeline")
    source_name = source.get("name", "")
    conference = source.get("conference", "")
    if source_type in {"html_press_room", "html_listing"}:
        return fetch_html_press_items(source, cutoff, terms, article_cache)

    xml_bytes = fetch_xml(source["url"])
    items: List[Dict[str, str]] = []
    for title, link, dt in parse_rss(xml_bytes):
        if not title:
            continue
        if dt and dt < cutoff:
            continue
        if not is_source_relevant(
            category,
            title,
            link,
            source_name=source_name,
            conference=conference,
        ):
            continue
        tracked_match, new_candidate = analyze_match(title, link, terms)
        if source.get("require_match", True) and not tracked_match and not new_candidate:
            continue
        match_label = tracked_match or (f"NEW: {new_candidate}" if new_candidate else "")
        items.append(
            {
                "title": title,
                "link": link,
                "date": dt.date().isoformat() if dt else "",
                "match": match_label,
            }
        )
    return items


def is_google_news_source(source: Dict[str, str]) -> bool:
    name = (source.get("name") or "").lower()
    url = (source.get("url") or "").lower()
    source_type = (source.get("source_type") or "").lower()
    return "google news" in name or "news.google.com" in url or source_type == "google_news_query"


def is_google_news_row(row: Dict[str, str]) -> bool:
    source = (row.get("source") or "").lower()
    link = (row.get("link") or "").lower()
    return "google news" in source or "news.google.com" in link


def main() -> int:
    parser = argparse.ArgumentParser(description="Update AFib weekly news rows")
    parser.add_argument(
        "--with-google-news",
        action="store_true",
        help="Include Google News feed queries in addition to company press rooms",
    )
    parser.add_argument(
        "--verbose-timing",
        action="store_true",
        help="Print per-source timing and item counts",
    )
    parser.add_argument(
        "--conference-only",
        action="store_true",
        help="Only scan conference sources",
    )
    parser.add_argument(
        "--conference",
        default="",
        help="Restrict conference scanning to one meeting code such as ACC, HRS, EHRA, ESC, or AHA",
    )
    args = parser.parse_args()

    if not SOURCES_PATH.exists():
        print("Missing data/news_sources.json")
        return 1

    terms = load_terms()
    registry_map = load_registry_ids()
    article_cache = load_article_cache()
    sources = json.loads(SOURCES_PATH.read_text())
    if args.conference_only:
        sources = [source for source in sources if source.get("category") == "conference_abstracts"]
    if not args.with_google_news:
        sources = [source for source in sources if not is_google_news_source(source)]
    if args.with_google_news:
        sources += build_google_news_sources(terms)
    now = datetime.now(timezone.utc)
    conference_filter = (args.conference or "").strip().upper()
    conference_sources = load_conference_sources(now)
    if conference_filter:
        conference_sources = [
            source for source in conference_sources if source.get("conference", "").upper() == conference_filter
        ]
    if not args.conference_only:
        sources += load_company_press_sources()
    sources += conference_sources
    default_cutoff = now - timedelta(days=7)

    existing = [
        row
        for row in read_existing()
        if is_af_relevant(row.get("title", ""), row.get("link", "")) and keep_row(row)
    ]
    if not args.with_google_news:
        existing = [row for row in existing if not is_google_news_row(row)]
    # Keep CI manual ClinicalTrials.gov rows tied to true CT.gov update dates.
    ctgov_date_cache: Dict[str, str] = {}
    for row in existing:
        link = row.get("link", "")
        source = (row.get("source") or "").lower()
        if "ci manual scan" not in source or "clinicaltrials.gov/study/" not in link.lower():
            continue
        nct_id = extract_nct_id(f"{row.get('title', '')} {link}")
        if not nct_id:
            continue
        if nct_id not in ctgov_date_cache:
            ctgov_date_cache[nct_id] = fetch_ctgov_last_update_date(nct_id)
        if ctgov_date_cache[nct_id]:
            row["date"] = ctgov_date_cache[nct_id]
    # Re-route regulatory items into the merged Regulatory+Safety column.
    for row in existing:
        if is_regulatory_item(row.get("title", ""), row.get("link", ""), row.get("source", "")):
            row["category"] = "safety_signals"
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
    source_timings: List[Tuple[float, str, int]] = []

    for source in sources:
        category = source.get("category")
        url = source.get("url")
        name = source.get("name")
        if category not in CATEGORIES or not url or not name:
            continue

        started_at = time.perf_counter()
        try:
            source_cutoff = now - timedelta(days=int(source.get("lookback_days", 7)))
            if source.get("category") != "conference_abstracts":
                source_cutoff = default_cutoff
            items = fetch_source_items(source, source_cutoff, terms, article_cache)
        except Exception as exc:  # noqa: BLE001
            elapsed = time.perf_counter() - started_at
            source_timings.append((elapsed, name, -1))
            if args.verbose_timing:
                print(f"[timing] {name}: {elapsed:.2f}s (error)", flush=True)
            print(f"Failed to fetch {name}: {exc}")
            continue
        elapsed = time.perf_counter() - started_at
        source_timings.append((elapsed, name, len(items)))
        if args.verbose_timing:
            print(f"[timing] {name}: {elapsed:.2f}s ({len(items)} items)", flush=True)

        for item in items:
            title = item.get("title", "")
            link = item.get("link", "")
            date_str = item.get("date", "")
            match = item.get("match", "")
            if not title:
                continue
            source_label = name if not match else f"{name} · Match: {match}"
            row = {
                "category": category,
                "title": title,
                "date": date_str,
                "source": source_label,
                "link": link,
            }
            if is_regulatory_item(title, link, source_label):
                row["category"] = "safety_signals"
            key = (row["category"], normalize_title(row["title"]), row["date"])
            if key in seen:
                continue
            seen.add(key)
            new_rows.append(row)

    new_rows.extend(manual_ci_rows(terms=terms, seen=seen, registry_map=registry_map))

    combined = dedupe_rows(existing + new_rows)
    write_rows(combined)
    save_article_cache(article_cache)
    if args.verbose_timing and source_timings:
        print("Slowest sources:", flush=True)
        for elapsed, name, count in sorted(source_timings, reverse=True)[:10]:
            count_label = "error" if count < 0 else f"{count} items"
            print(f"- {name}: {elapsed:.2f}s ({count_label})", flush=True)
    print(f"Added {len(new_rows)} new weekly updates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
