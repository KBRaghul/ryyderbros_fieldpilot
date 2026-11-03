"""Generate a verified report for every demo field and save it to disk.

The API serves these saved reports first, so the live site keeps working when the
LLM budget runs out. Run it while there is budget, then commit the files.

Usage:
    python -m app.agent.save_reports                  # every field
    python -m app.agent.save_reports elmore_corn_1    # one field
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app.agent.report import generate_report
from app.tools.sentinel import FIELDS_DIR

REPORTS_DIR = Path(__file__).resolve().parents[2] / "data" / "reports"
PAUSE_S = 5  # pause between fields to stay under the free tier rate limit


def report_path(fid):
    return REPORTS_DIR / f"{fid}.json"


def load_saved_report(fid):
    """The saved report for a field, or None if there is none."""
    path = report_path(fid)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def main():
    names = sys.argv[1:] or sorted(p.stem for p in FIELDS_DIR.glob("*.geojson"))
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    for i, fid in enumerate(names):
        if i:
            time.sleep(PAUSE_S)
        try:
            result = generate_report(fid)
        except Exception as e:
            print(f"{fid}: FAILED ({type(e).__name__}: {e}). Kept the old saved report, if any.")
            continue
        result["saved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        report_path(fid).write_text(json.dumps(result, indent=2))
        status = "verified" if result["verified"] else f"NEEDS REVIEW {result['unsupported_numbers'] + result['issues']}"
        print(f"{fid}: saved, {status}")


if __name__ == "__main__":
    main()
