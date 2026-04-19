#!/usr/bin/env python3
import csv
import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "afib.json"
CSV_PATH = ROOT / "data" / "weekly_updates.csv"

CATEGORIES = {
    "safety_signals",
    "label_expansions",
    "guideline_updates",
    "conference_abstracts",
    "press_pipeline",
}
MAX_ITEMS_PER_CATEGORY = 12


def normalize_title(title: str) -> str:
    base = re.split(r"\s[-|\u2014]\s", title, maxsplit=1)[0]
    base = base.lower()
    base = re.sub(r"[^a-z0-9\s]", " ", base)
    return re.sub(r"\s+", " ", base).strip()


def extract_match(source: str) -> str:
    m = re.search(r"match:\s*(.+)$", source or "", flags=re.IGNORECASE)
    return (m.group(1).strip().lower() if m else "")


def source_priority(source: str) -> int:
    value = (source or "").lower()
    if "press release" in value or "press releases" in value or "mediaroom" in value:
        return 1
    if "fda" in value or "ema" in value:
        return 2
    if "google news" in value:
        return 4
    return 3


def parse_iso_date(raw: str):
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except Exception:
        return None


def week_bucket(raw: str) -> str:
    dt = parse_iso_date(raw)
    if dt is None:
        return "unknown"
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def sort_key(entry):
    dt = parse_iso_date(entry.get("date", ""))
    ord_date = dt.toordinal() if dt else 0
    # Lower source rank is better; higher date is better.
    return (-ord_date, source_priority(entry.get("source", "")), -len(entry.get("title", "")))


def event_type(title: str) -> str:
    t = (title or "").lower()
    if any(k in t for k in ["approval", "approved", "ce mark", "clearance", "pma", "510(k)", "patent"]):
        return "regulatory"
    if any(k in t for k in ["topline", "readout", "results"]):
        return "readout"
    if any(k in t for k in ["enrollment", "first patient", "recruiting", "trial"]):
        return "trial_progress"
    if "guideline" in t:
        return "guideline"
    if "safety" in t:
        return "safety"
    return "general"


def prefer(new_entry, old_entry) -> bool:
    new_rank = source_priority(new_entry.get("source", ""))
    old_rank = source_priority(old_entry.get("source", ""))
    if new_rank != old_rank:
        return new_rank < old_rank

    new_date = parse_iso_date(new_entry.get("date", ""))
    old_date = parse_iso_date(old_entry.get("date", ""))
    if new_date and old_date and new_date != old_date:
        return new_date > old_date
    if new_date and not old_date:
        return True
    if old_date and not new_date:
        return False
    return len(new_entry.get("title", "")) > len(old_entry.get("title", ""))


def dedupe_entries(entries):
    # Keep newest items first when date is present.
    entries = sorted(entries, key=lambda e: e.get("date", ""), reverse=True)

    best = {}
    for entry in entries:
        title = entry.get("title", "")
        date = entry.get("date", "")
        source = entry.get("source", "")
        match = extract_match(source)
        if match:
            key = ("asset_event_week", match, event_type(title), week_bucket(date))
        else:
            key = ("title_week", normalize_title(title), week_bucket(date))

        current = best.get(key)
        if current is None or prefer(entry, current):
            best[key] = entry

    return list(best.values())


def top_entries_by_category(rows_by_category):
    weekly = {key: [] for key in CATEGORIES}
    for category, entries in rows_by_category.items():
        weekly[category] = dedupe_entries(entries)

    global_seen = set()
    category_order = [
        "safety_signals",
        "label_expansions",
        "guideline_updates",
        "conference_abstracts",
        "press_pipeline",
    ]
    for category in category_order:
        unique_entries = []
        seen_by_week = {}
        for entry in weekly.get(category, []):
            key = (normalize_title(entry.get("title", "")), entry.get("date", ""))
            week_key = (
                category,
                extract_match(entry.get("source", "")),
                event_type(entry.get("title", "")),
                week_bucket(entry.get("date", "")),
            )
            if key in global_seen:
                continue
            prior = seen_by_week.get(week_key)
            if prior is not None and not prefer(entry, prior):
                continue
            if prior is not None and prefer(entry, prior):
                try:
                    unique_entries.remove(prior)
                except ValueError:
                    pass
            seen_by_week[week_key] = entry
            global_seen.add(key)
            unique_entries.append(entry)
        weekly[category] = sorted(unique_entries, key=sort_key)[:MAX_ITEMS_PER_CATEGORY]
    return weekly


def assert_weekly_sync(expected_weekly, actual_weekly):
    missing = []
    for category in CATEGORIES:
        actual_keys = {
            (normalize_title(entry.get("title", "")), entry.get("date", ""), entry.get("link", ""))
            for entry in actual_weekly.get(category, [])
        }
        for entry in expected_weekly.get(category, []):
            key = (normalize_title(entry.get("title", "")), entry.get("date", ""), entry.get("link", ""))
            if key not in actual_keys:
                missing.append((category, entry.get("title", ""), entry.get("date", ""), entry.get("link", "")))
    if missing:
        lines = ["weekly_updates sync check failed. Missing rows in afib.json:"]
        for category, title, date, link in missing[:10]:
            lines.append(f"- {category} | {date or 'Date TBD'} | {title} | {link}")
        raise SystemExit("\n".join(lines))


def main() -> int:
    if not DATA_PATH.exists() or not CSV_PATH.exists():
        print("Missing data/afib.json or data/weekly_updates.csv")
        return 1

    data = json.loads(DATA_PATH.read_text())

    weekly = {key: [] for key in CATEGORIES}

    with CSV_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            category = (row.get("category") or "").strip()
            if category not in CATEGORIES:
                continue
            weekly[category].append(
                {
                    "title": (row.get("title") or "").strip(),
                    "date": (row.get("date") or "").strip(),
                    "source": (row.get("source") or "").strip(),
                    "link": (row.get("link") or "").strip(),
                }
            )

    weekly = top_entries_by_category(weekly)

    data["weekly_updates"] = weekly
    DATA_PATH.write_text(json.dumps(data, indent=2))
    reloaded = json.loads(DATA_PATH.read_text())
    assert_weekly_sync(weekly, reloaded.get("weekly_updates", {}))
    print("Updated weekly_updates from CSV.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
