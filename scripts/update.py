#!/usr/bin/env python3
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "afib.json"
WATCHLIST_PATH = ROOT / "data" / "watchlist.json"


def fetch_json(url: str) -> Dict[str, Any]:
  req = urllib.request.Request(url, headers={"User-Agent": "AFib-Dashboard-Update/1.0"})
  with urllib.request.urlopen(req, timeout=20) as resp:
    return json.load(resp)


def get_trial_status(nct_id: str) -> Dict[str, Optional[str]]:
  url = f"https://clinicaltrials.gov/api/v2/studies/{nct_id}"
  data = fetch_json(url)
  status = data.get("protocolSection", {}).get("statusModule", {})

  def pick(struct_key: str) -> Optional[str]:
    struct = status.get(struct_key, {})
    return struct.get("date")

  return {
    "overall_status": status.get("overallStatus"),
    "last_update": pick("lastUpdatePostDateStruct"),
    "primary_completion": pick("primaryCompletionDateStruct"),
    "completion": pick("completionDateStruct"),
  }


def update_trial(item: Dict[str, Any], watch: Dict[str, str], status: Dict[str, Optional[str]]):
  trial_name = watch.get("trial_name")
  matching = None
  for trial in item.get("trials", []):
    if trial.get("name") == trial_name:
      matching = trial
      break

  if not matching:
    matching = {
      "name": trial_name,
      "phase": "",
      "status": "",
      "readout": "TBD",
      "readout_date": None,
      "registry_id": watch.get("nct_id"),
      "note": watch.get("note", ""),
    }
    item.setdefault("trials", []).append(matching)

  if status.get("overall_status"):
    matching["status"] = status["overall_status"]

  if status.get("primary_completion"):
    matching["readout_date"] = status["primary_completion"]

  if status.get("last_update"):
    item["latest_update"] = f"ClinicalTrials.gov update posted {status['last_update']}"


def main() -> int:
  if not DATA_PATH.exists() or not WATCHLIST_PATH.exists():
    print("Missing data files.")
    return 1

  data = json.loads(DATA_PATH.read_text())
  watchlist = json.loads(WATCHLIST_PATH.read_text())

  items_by_id = {item["id"]: item for item in data.get("items", [])}

  for watch in watchlist.get("clinical_trials", []):
    nct_id = watch.get("nct_id")
    if not nct_id:
      continue
    item_id = watch.get("item_id")
    item = items_by_id.get(item_id)
    if not item:
      continue
    try:
      status = get_trial_status(nct_id)
    except Exception as exc:  # noqa: BLE001
      print(f"Failed to fetch {nct_id}: {exc}")
      continue
    update_trial(item, watch, status)

  data["as_of"] = date.today().isoformat()
  DATA_PATH.write_text(json.dumps(data, indent=2))
  print("Updated", DATA_PATH)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
