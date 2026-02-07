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

## Data model

- `data/afib.json` is the dashboard data source.
- Each item contains `trials`, `latest_update`, and `sources` for provenance.

## Adding new competitors

Add a new object to `data/afib.json` with:

- `id`, `name`, `type`, `category`, `stage`, `mechanism`, `focus`, `company`
- `latest_update`, `tags`, `trials`, `notes`, `sources`

The UI auto-updates and new filters appear automatically.
