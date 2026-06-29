"""Evaluate genuine passports through the eKYC document pipeline.

Runs PassportFraudAnalyzer over a folder of genuine passport images and reports
how many are detected as REAL (status == "passed"), the MRZ read rate, and the
reasons for any rejections. Use with the MIDV-2020 passport set installed via
`install_test_dataset.py --prepare-midv2020`.

Usage (from repo root):
    PYTHONPATH=backend .venv/bin/python scripts/evaluate_genuine_passports.py \
        [test_dataset/genuine_midv2020_passport]
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "test_dataset" / "genuine_midv2020_passport"
OUT_DIR = ROOT / "outputs" / "genuine_passport_eval"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def main() -> int:
    sys.path.insert(0, str(ROOT / "backend"))
    from app.services.fraud import PassportFraudAnalyzer

    folder = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_DIR
    imgs = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS) if folder.exists() else []
    if not imgs:
        print(f"No images in {folder}.")
        print("Install genuine passports first, e.g.:")
        print("  python scripts/install_test_dataset.py --prepare-midv2020 <extracted-midv-2020-dir>")
        return 0

    analyzer = PassportFraudAnalyzer()
    passed = 0
    mrz_read = 0
    mrz_valid = 0
    sig_counter: Counter = Counter()
    rows = []
    for p in imgs:
        a = analyzer.analyze(p.read_bytes(), p.name)
        codes = [s.code for s in a.signals]
        if a.status == "passed":
            passed += 1
        if a.ocr and a.ocr.mrz_text:
            mrz_read += 1
        if a.ocr and a.ocr.mrz_valid:
            mrz_valid += 1
        for c in codes:
            sig_counter[c] += 1
        rows.append({
            "filename": p.name,
            "status": a.status,
            "mrz_read": bool(a.ocr and a.ocr.mrz_text),
            "mrz_valid": (a.ocr.mrz_valid if a.ocr else None),
            "quality": round(a.image_quality_score, 3),
            "fraud_risk": round(a.fraud_risk_score, 3),
            "signals": "|".join(codes),
        })

    n = len(imgs)
    summary = {
        "folder": str(folder.relative_to(ROOT)),
        "total": n,
        "detected_as_real_passed": passed,
        "detected_as_real_rate": round(passed / n, 4),
        "mrz_read_rate": round(mrz_read / n, 4),
        "mrz_valid_rate": round(mrz_valid / n, 4),
        "top_signals": sig_counter.most_common(10),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with (OUT_DIR / "results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(json.dumps(summary, indent=2))
    print(f"\nCSV: {OUT_DIR / 'results.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
