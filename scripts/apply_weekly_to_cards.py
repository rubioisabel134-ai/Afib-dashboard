#!/usr/bin/env python3
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
AFIB_PATH = ROOT / "data" / "afib.json"
CSV_PATH = ROOT / "data" / "weekly_updates.csv"


def parse_date(raw: str) -> Optional[datetime]:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def normalize(text: str) -> str:
    return text.lower()


def main() -> int:
    if not AFIB_PATH.exists() or not CSV_PATH.exists():
        print("Missing data files.")
        return 1

    data = json.loads(AFIB_PATH.read_text())
    items = data.get("items", [])

    # Build match terms
    terms = []
    for item in items:
        name = (item.get("name") or "").strip()
        company = (item.get("company") or "").strip()
        if name:
            terms.append(("name", name, item))
        if company:
            terms.append(("company", company, item))

    updates_by_item = {}

    with CSV_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            title = (row.get("title") or "").strip()
            if not title:
                continue
            date_str = (row.get("date") or "").strip()
            dt = parse_date(date_str)
            link = (row.get("link") or "").strip()
            category = (row.get("category") or "").strip()
            source = (row.get("source") or "").strip()

            title_norm = normalize(title)

            matched_items = []
            for kind, term, item in terms:
                if normalize(term) in title_norm:
                    matched_items.append((kind, term, item))

            if not matched_items:
                continue

            for kind, term, item in matched_items:
                key = item.get("id")
                if not key:
                    continue
                existing = updates_by_item.get(key)
                if existing is None or (dt and existing["date"] and dt > existing["date"]):
                    updates_by_item[key] = {
                        "title": title,
                        "date": dt,
                        "date_str": date_str,
                        "link": link,
                        "category": category,
                        "source": source,
                    }

    # Apply updates
    for item in items:
        key = item.get("id")
        if not key or key not in updates_by_item:
            continue
        if item.get("auto_news") is False:
            continue
        if item.get("type") == "Drug" and "generic" in (item.get("company") or "").lower():
            continue
        update = updates_by_item[key]
        date_prefix = f"{update['date_str']}: " if update["date_str"] else ""
        item["latest_update"] = f"{date_prefix}{update['title']}"

        if update["link"]:
            sources = item.get("sources") or []
            if update["link"] not in sources:
                sources.append(update["link"])
                item["sources"] = sources

        # Mark press_2026 if press_pipeline and 2026 date
        if update["category"] == "press_pipeline" and update["date"] and update["date"].year == 2026:
            item["press_2026"] = True

    data["items"] = items
    AFIB_PATH.write_text(json.dumps(data, indent=2))
    print("Applied weekly updates to cards.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
