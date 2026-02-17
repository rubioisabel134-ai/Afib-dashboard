#!/usr/bin/env python3
import csv
import json
import re
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


def normalize_title(title: str) -> str:
    base = re.split(r"\s[-|\u2014]\s", title, maxsplit=1)[0]
    base = base.lower()
    base = re.sub(r"[^a-z0-9\s]", " ", base)
    return re.sub(r"\s+", " ", base).strip()


def dedupe_entries(entries):
    def extract_match(source: str) -> str:
        m = re.search(r"match:\s*(.+)$", source, flags=re.IGNORECASE)
        return (m.group(1).strip().lower() if m else "")

    # Keep newest items first when date is present.
    entries = sorted(entries, key=lambda e: e.get("date", ""), reverse=True)

    best = {}
    for entry in entries:
        title = entry.get("title", "")
        date = entry.get("date", "")
        source = entry.get("source", "")
        match = extract_match(source)
        if match:
            key = ("match_date", match, date)
        else:
            key = ("title_date", normalize_title(title), date)

        current = best.get(key)
        if current is None or len(title) > len(current.get("title", "")):
            best[key] = entry

    return list(best.values())


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
                }
            )

    for category in CATEGORIES:
        weekly[category] = dedupe_entries(weekly[category])

    # Remove cross-category duplicates so the same story appears once.
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
        for entry in weekly.get(category, []):
            key = (normalize_title(entry.get("title", "")), entry.get("date", ""))
            if key in global_seen:
                continue
            global_seen.add(key)
            unique_entries.append(entry)
        weekly[category] = unique_entries

    data["weekly_updates"] = weekly
    DATA_PATH.write_text(json.dumps(data, indent=2))
    print("Updated weekly_updates from CSV.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
