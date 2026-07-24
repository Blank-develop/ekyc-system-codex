#!/usr/bin/env python3
"""Count readable passport MRZ records in a labelled JPG dataset.

Uses the production PassportFraudAnalyzer OCR path. TXT files are read only as
ground truth and to exclude face-only/non-passport JPGs; they are never sent to
OCR. Results are written to outputs/passport_ocr_full_evaluation/.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import multiprocessing
import os
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.services.fraud import PassportFraudAnalyzer  # noqa: E402
from evaluate_passport_ocr_dataset import _name_tokens, parse_ground_truth  # noqa: E402

_ANALYZER: PassportFraudAnalyzer | None = None


def _initialize_worker() -> None:
    global _ANALYZER
    _ANALYZER = PassportFraudAnalyzer()


def _evaluate_one(item: tuple[str, str, str]) -> dict[str, object]:
    global _ANALYZER
    base, image_path, label_path = item
    if _ANALYZER is None:
        _initialize_worker()
    assert _ANALYZER is not None

    gt = parse_ground_truth(Path(label_path).read_text(encoding="utf-8", errors="replace"))
    started = time.perf_counter()
    try:
        analysis = _ANALYZER.analyze(Path(image_path).read_bytes(), Path(image_path).name)
        ocr = analysis.ocr
        gt_name = _name_tokens(gt.surname, gt.given_name)
        got_name = _name_tokens(ocr.full_name)
        return {
            "base": base,
            "error": "",
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "mrz_found": bool(analysis.checks.get("mrz_found")),
            "mrz_valid": bool(ocr.mrz_valid),
            "passport_number_correct": bool(
                gt.passport_number
                and ocr.passport_number
                and gt.passport_number == ocr.passport_number.replace("<", "").upper()
            ),
            "name_correct": bool(gt_name and gt_name == got_name),
            "nationality_correct": bool(
                gt.nationality and ocr.nationality and gt.nationality == ocr.nationality.upper()
            ),
            "date_of_birth_correct": bool(
                gt.date_of_birth and ocr.date_of_birth and gt.date_of_birth == ocr.date_of_birth
            ),
            "expiry_date_correct": bool(
                gt.expiry_date and ocr.expiry_date and gt.expiry_date == ocr.expiry_date
            ),
            "reason": ",".join(signal.code for signal in analysis.signals),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "base": base,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "mrz_found": False,
            "mrz_valid": False,
            "passport_number_correct": False,
            "name_correct": False,
            "nationality_correct": False,
            "date_of_birth_correct": False,
            "expiry_date_correct": False,
            "reason": "",
        }


def _copy_suffix(stem: str) -> bool:
    return bool(re.search(r" \(\d+\)$", stem))


def _metric_summary(results: list[dict[str, object]]) -> dict[str, object]:
    fields = [
        "passport_number_correct",
        "name_correct",
        "nationality_correct",
        "date_of_birth_correct",
        "expiry_date_correct",
    ]
    total = len(results)
    counts = {field: sum(bool(row[field]) for row in results) for field in fields}
    return {
        "images": total,
        "ocr_errors": sum(bool(row["error"]) for row in results),
        "mrz_read": sum(bool(row["mrz_found"]) for row in results),
        "mrz_valid": sum(bool(row["mrz_valid"]) for row in results),
        "mrz_unread": total - sum(bool(row["mrz_found"]) for row in results),
        "mrz_invalid_or_unread": total - sum(bool(row["mrz_valid"]) for row in results),
        "field_correct": counts,
        "mrz_read_rate": round(sum(bool(row["mrz_found"]) for row in results) / max(total, 1), 4),
        "mrz_valid_rate": round(sum(bool(row["mrz_valid"]) for row in results) / max(total, 1), 4),
        "field_accuracy": {
            field: round(count / max(total, 1), 4) for field, count in counts.items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=ROOT / "passport")
    parser.add_argument("--workers", type=int, default=min(6, os.cpu_count() or 2))
    parser.add_argument("--limit", type=int, default=0, help="0 evaluates every passport")
    args = parser.parse_args()

    folder = args.dir.resolve()
    jpgs = {path.stem: path for path in folder.iterdir() if path.suffix.lower() == ".jpg"}
    txts = {path.stem: path for path in folder.iterdir() if path.suffix.lower() == ".txt"}
    paired = sorted(set(jpgs) & set(txts))

    passport_items: list[tuple[str, str, str]] = []
    face_or_nonpassport = 0
    for base in paired:
        gt = parse_ground_truth(txts[base].read_text(encoding="utf-8", errors="replace"))
        if not (gt.mrz_line1 and gt.mrz_line2):
            face_or_nonpassport += 1
            continue
        passport_items.append((base, str(jpgs[base]), str(txts[base])))

    if args.limit > 0:
        passport_items = passport_items[: args.limit]
    if not passport_items:
        print(f"No labelled passport JPGs found in {folder}")
        return 1

    print(f"JPG files                 : {len(jpgs)}", flush=True)
    print(f"Labelled passport JPGs    : {len(passport_items)}", flush=True)
    print(f"Face/non-passport skipped : {face_or_nonpassport}", flush=True)
    print(f"Unpaired JPGs skipped     : {len(set(jpgs) - set(txts))}", flush=True)
    # Exact-byte duplicates are deterministic for the OCR pipeline. Analyze one
    # canonical file per hash, preferring the filename without a copy suffix,
    # then expand that result back to every labelled filename in results.csv.
    # This keeps the all-file audit complete without inflating compute time or
    # hiding duplicate records from the accuracy report.
    hash_groups: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for item in passport_items:
        digest = hashlib.sha256(Path(item[1]).read_bytes()).hexdigest()
        hash_groups[digest].append(item)

    canonical_items: list[tuple[str, str, str]] = []
    canonical_by_base: dict[str, str] = {}
    hash_by_base: dict[str, str] = {}
    duplicate_groups: list[dict[str, object]] = []
    for digest, group in sorted(hash_groups.items()):
        ordered = sorted(group, key=lambda item: (_copy_suffix(item[0]), item[0]))
        canonical = ordered[0]
        canonical_items.append(canonical)
        duplicate_groups.append(
            {
                "sha256": digest,
                "canonical": canonical[0],
                "files": [item[0] for item in ordered],
            }
        )
        for item in ordered:
            canonical_by_base[item[0]] = canonical[0]
            hash_by_base[item[0]] = digest

    duplicate_groups = [group for group in duplicate_groups if len(group["files"]) > 1]
    duplicate_records = len(passport_items) - len(canonical_items)

    print(f"Unique passport images    : {len(canonical_items)}", flush=True)
    print(f"Exact duplicate records   : {duplicate_records}", flush=True)
    print(f"Workers                   : {max(1, args.workers)}", flush=True)

    started = time.perf_counter()
    results: list[dict[str, object]] = []
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=max(1, args.workers),
        mp_context=context,
        initializer=_initialize_worker,
    ) as executor:
        for index, result in enumerate(executor.map(_evaluate_one, canonical_items), 1):
            results.append(result)
            if index == 1 or index % 25 == 0 or index == len(canonical_items):
                found = sum(bool(row["mrz_found"]) for row in results)
                valid = sum(bool(row["mrz_valid"]) for row in results)
                print(f"[{index}/{len(canonical_items)}] MRZ read={found}, valid={valid}", flush=True)

    unique_results = results
    result_by_base = {str(row["base"]): row for row in unique_results}
    results = []
    for base, _image_path, _label_path in passport_items:
        canonical = canonical_by_base[base]
        row = dict(result_by_base[canonical])
        row["base"] = base
        row["sha256"] = hash_by_base[base]
        row["is_duplicate"] = base != canonical
        row["duplicate_of"] = canonical if base != canonical else ""
        row["filename_copy_pattern"] = _copy_suffix(base)
        if base != canonical:
            row["elapsed_seconds"] = 0.0
        results.append(row)

    total = len(results)
    elapsed = time.perf_counter() - started
    all_metrics = _metric_summary(results)
    unique_metrics = _metric_summary(unique_results)
    summary = {
        "folder": str(folder),
        "jpg_files": len(jpgs),
        "passport_images_evaluated": total,
        "unique_passport_images_evaluated": len(unique_results),
        "exact_duplicate_passport_records": duplicate_records,
        "exact_duplicate_passport_groups": len(duplicate_groups),
        "face_or_nonpassport_skipped": face_or_nonpassport,
        "unpaired_jpg_skipped": len(set(jpgs) - set(txts)),
        "all_labelled_files": all_metrics,
        "unique_content_only": unique_metrics,
        "elapsed_seconds": round(elapsed, 2),
    }

    output_dir = ROOT / "outputs" / "passport_ocr_full_evaluation"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (output_dir / "duplicate_groups.json").write_text(
        json.dumps(duplicate_groups, indent=2),
        encoding="utf-8",
    )
    with (output_dir / "results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(results)
    unique_csv_rows: list[dict[str, object]] = []
    for row in unique_results:
        expanded = dict(row)
        base = str(row["base"])
        expanded.update(
            {
                "sha256": hash_by_base[base],
                "is_duplicate": False,
                "duplicate_of": "",
                "filename_copy_pattern": _copy_suffix(base),
            }
        )
        unique_csv_rows.append(expanded)
    with (output_dir / "unique_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(unique_csv_rows[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(unique_csv_rows)

    print("\n" + json.dumps(summary, indent=2), flush=True)
    print(f"Results: {output_dir / 'results.csv'}", flush=True)
    print(f"Unique results: {output_dir / 'unique_results.csv'}", flush=True)
    print(f"Duplicate groups: {output_dir / 'duplicate_groups.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
