# AFib Intelligence Dashboard

A curated AFib landscape dashboard focused on anti-arrhythmic drugs, stroke prevention therapies, ablation systems, and LAA occlusion devices.

## Run locally

```bash
cd /Users/isabelschlaepfer/afib-dashboard
python3 -m http.server 8000
```

Then open `http://localhost:8000` in a browser.

## Weekly update workflow

1. Update `data/watchlist.json` with NCT IDs for trials you want tracked.
2. Run the updater:

```bash
python3 scripts/update.py
```

The script pulls trial status updates from ClinicalTrials.gov and refreshes `data/afib.json`.

## One-click weekly update

Run this from the repo root:

```bash
scripts/weekly.sh
```

It runs the updater, commits changes, and pushes to `origin/main`.

## Weekly intel (safety, labels, guidelines, abstracts)

Edit `data/weekly_updates.csv` and run:

```bash
python3 scripts/update_weekly.py
```

This refreshes the `weekly_updates` block in `data/afib.json`.

## Auto news + company press feeds

Weekly news pulls from FDA/EMA + Google News and adds items to `data/weekly_updates.csv`:

```bash
python3 scripts/update_news.py
```

To include company press RSS feeds, add them to `data/company_press.json`:

```json
[
  { "name": "Boston Scientific Press", "url": "https://news.bostonscientific.com/rss" }
]
```

The updater will tag items with a matched drug/device/company when possible.

## Data model

- `data/afib.json` is the dashboard data source.
- Each item contains `trials`, `latest_update`, and `sources` for provenance.

## Adding new competitors

Add a new object to `data/afib.json` with:

- `id`, `name`, `type`, `category`, `stage`, `mechanism`, `focus`, `company`
- `latest_update`, `tags`, `trials`, `notes`, `sources`

The UI auto-updates and new filters appear automatically.
