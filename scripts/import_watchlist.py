"""Import a government watchlist ("blacklist") into the Kyron biographic screener.

Accepts CSV or JSON. Recognised fields (extra columns are ignored):

    full_name          (required)
    date_of_birth      yyyy-mm-dd
    nationality        3-letter code
    passport_numbers   one or more, separated by , ; or |
    source_ref         the authority's own record id
    reason             why the person is listed
    severity           high | medium | low   (default: high)
    source             list name / version
    notes

CSV example (header row required):

    full_name,date_of_birth,nationality,passport_numbers,source_ref,reason
    MURRAY ROSS SMITH,1962-12-14,AUS,PB5870043,RN-2024-001,Interpol Red Notice
    JOHN DOE,1990-01-01,USA,"X1234567;Y7654321",NW-88,National watchlist

JSON: a list of objects with the same keys (passport_numbers may be a list).

Usage (from repo root):
    PYTHONPATH=backend .venv/bin/python scripts/import_watchlist.py <file.csv|file.json> [--replace] [--source "NAME v1"]

--replace clears the existing list first (use for a full fresh feed; omit to append).
The database is taken from DATABASE_URL, same as the running app.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def load_records(path: Path) -> list[dict]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("subjects") or data.get("records") or []
        return list(data)
    # CSV
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    ap = argparse.ArgumentParser(description="Import a government watchlist for biographic screening.")
    ap.add_argument("file", type=Path, help="CSV or JSON watchlist export")
    ap.add_argument("--replace", action="store_true", help="clear the existing list first")
    ap.add_argument("--source", default=None, help="list name / version to stamp on each entry")
    args = ap.parse_args()

    if not args.file.exists():
        print(f"File not found: {args.file}")
        return 1

    records = load_records(args.file)
    if not records:
        print("No records found in the file.")
        return 1

    from app.services.watchlist_store import watchlist_store

    written = watchlist_store.import_subjects(records, source=args.source, replace=args.replace)
    summary = watchlist_store.summary()
    print(f"Imported {written} subject(s) ({'replaced list' if args.replace else 'appended'}).")
    print(f"List now holds {summary['subject_count']} subject(s), {summary['active_subject_count']} active.")
    print("\nRemember: set LALIGENCE_WATCHLIST_ENABLED=true so screening runs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
