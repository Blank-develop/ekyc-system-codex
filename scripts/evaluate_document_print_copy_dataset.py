from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from app.models.schemas import DocumentAnalysis
from app.services.fraud import LaoIdCardFraudAnalyzer, PassportFraudAnalyzer


ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = ROOT / "test_dataset" / "document_print_copy"
OUTPUT_DIR = ROOT / "outputs" / "document_print_copy_eval"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass(frozen=True)
class DatasetCase:
    folder: str
    document_type: str
    expected_label: str


CASES = (
    DatasetCase("real_camera_passport", "passport", "real"),
    DatasetCase("real_camera_lao_id", "lao_id_card", "real"),
    DatasetCase("fake_printed_passport_on_paper", "passport", "fake"),
    DatasetCase("fake_printed_lao_id_on_paper", "lao_id_card", "fake"),
)


def image_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS)


def signal_codes(analysis: DocumentAnalysis) -> list[str]:
    return [signal.code for signal in analysis.signals]


def predict_label(analysis: DocumentAnalysis) -> str:
    codes = set(signal_codes(analysis))
    if analysis.status == "rejected" or "DOCUMENT_PRINT_COPY_RISK_HIGH" in codes:
        return "fake"
    return "real"


def analyze_file(path: Path, document_type: str) -> DocumentAnalysis:
    analyzer = PassportFraudAnalyzer() if document_type == "passport" else LaoIdCardFraudAnalyzer()
    return analyzer.analyze(path.read_bytes(), path.name)


def row_for(path: Path, case: DatasetCase, analysis: DocumentAnalysis) -> dict[str, str | float | int]:
    codes = signal_codes(analysis)
    predicted = predict_label(analysis)
    print_score = float(analysis.checks.get("model_heuristic_print_copy_v1_score") or 0.0)
    print_reason = str(analysis.checks.get("model_heuristic_print_copy_v1_reason") or "")
    return {
        "folder": case.folder,
        "filename": path.name,
        "document_type": case.document_type,
        "expected": case.expected_label,
        "predicted": predicted,
        "correct": int(predicted == case.expected_label),
        "status": analysis.status,
        "quality": analysis.image_quality_score,
        "fraud_risk": analysis.fraud_risk_score,
        "document_likeness": analysis.document_likeness_score,
        "print_copy_score": round(print_score, 3),
        "print_copy_high": int("DOCUMENT_PRINT_COPY_RISK_HIGH" in codes),
        "print_copy_medium": int("DOCUMENT_PRINT_COPY_RISK_MEDIUM" in codes),
        "signals": "|".join(codes),
        "print_copy_reason": print_reason,
    }


def summarize(rows: list[dict[str, str | float | int]]) -> dict[str, object]:
    total = len(rows)
    correct = sum(int(row["correct"]) for row in rows)
    real_rows = [row for row in rows if row["expected"] == "real"]
    fake_rows = [row for row in rows if row["expected"] == "fake"]
    false_rejects = [row for row in real_rows if row["predicted"] == "fake"]
    false_accepts = [row for row in fake_rows if row["predicted"] == "real"]
    print_hits = [row for row in fake_rows if int(row["print_copy_high"]) == 1]
    return {
        "total_images": total,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "real_images": len(real_rows),
        "fake_images": len(fake_rows),
        "false_rejects": len(false_rejects),
        "false_accepts": len(false_accepts),
        "printed_copy_high_detection_rate": round(len(print_hits) / len(fake_rows), 4) if fake_rows else 0.0,
        "misclassified": [
            {
                "folder": row["folder"],
                "filename": row["filename"],
                "expected": row["expected"],
                "predicted": row["predicted"],
                "status": row["status"],
                "print_copy_score": row["print_copy_score"],
                "signals": row["signals"],
            }
            for row in rows
            if row["correct"] == 0
        ],
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str | float | int]] = []

    for case in CASES:
        folder = DATASET_ROOT / case.folder
        files = image_files(folder)
        if not files:
            print(f"No images found in {folder}")
            continue
        for path in files:
            analysis = analyze_file(path, case.document_type)
            rows.append(row_for(path, case, analysis))

    csv_path = OUTPUT_DIR / "results.csv"
    json_path = OUTPUT_DIR / "summary.json"

    if rows:
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    summary = summarize(rows)
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    print(f"\nCSV: {csv_path}")
    print(f"Summary: {json_path}")


if __name__ == "__main__":
    main()
