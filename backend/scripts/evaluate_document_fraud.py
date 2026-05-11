from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from app.services.fraud import PassportFraudAnalyzer


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def expected_label(path: Path, dataset_root: Path) -> str:
    top_level = path.relative_to(dataset_root).parts[0]
    return "genuine" if top_level.startswith("genuine") else "fraud"


def collect_images(dataset_root: Path, only_folder: str | None = None) -> list[Path]:
    images = sorted(
        path
        for path in dataset_root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in IMAGE_EXTENSIONS
        and not any(part.startswith("_") for part in path.relative_to(dataset_root).parts)
    )
    if only_folder:
        images = [path for path in images if path.relative_to(dataset_root).parts[0] == only_folder]
    return images


def percentage(value: float) -> str:
    return f"{value * 100:.1f}%"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate document fraud detection on a labeled folder dataset.")
    parser.add_argument("--dataset", default="test_dataset", help="Dataset root with genuine/ and fraud_* folders.")
    parser.add_argument("--only-folder", help="Evaluate only one top-level dataset folder, e.g. fraud_crop_replace.")
    parser.add_argument("--csv", default="test_dataset/evaluation_results.csv", help="CSV output path.")
    args = parser.parse_args()

    dataset_root = Path(args.dataset).resolve()
    if not dataset_root.exists():
        raise SystemExit(f"Dataset folder does not exist: {dataset_root}")

    images = collect_images(dataset_root, args.only_folder)
    if not images:
        detail = f" matching folder {args.only_folder!r}" if args.only_folder else ""
        raise SystemExit(f"No images found under {dataset_root}{detail}")

    analyzer = PassportFraudAnalyzer()
    rows: list[dict[str, str | float]] = []
    counts = {
        "true_accept": 0,
        "false_reject": 0,
        "true_reject": 0,
        "false_accept": 0,
    }
    by_folder: dict[str, dict[str, int]] = {}

    for image_path in images:
        label = expected_label(image_path, dataset_root)
        analysis = analyzer.analyze(image_path.read_bytes(), image_path.name)
        predicted = "fraud" if analysis.status == "rejected" else "genuine"
        folder = image_path.relative_to(dataset_root).parts[0]
        by_folder.setdefault(folder, {"total": 0, "correct": 0, "rejected": 0, "passed": 0})
        by_folder[folder]["total"] += 1
        by_folder[folder]["rejected" if analysis.status == "rejected" else "passed"] += 1

        if label == "genuine" and predicted == "genuine":
            counts["true_accept"] += 1
            by_folder[folder]["correct"] += 1
        elif label == "genuine" and predicted == "fraud":
            counts["false_reject"] += 1
        elif label == "fraud" and predicted == "fraud":
            counts["true_reject"] += 1
            by_folder[folder]["correct"] += 1
        else:
            counts["false_accept"] += 1

        rows.append(
            {
                "path": str(image_path.relative_to(dataset_root)),
                "expected": label,
                "predicted": predicted,
                "status": analysis.status,
                "fraud_risk": analysis.fraud_risk_score,
                "quality": analysis.image_quality_score,
                "document_likeness": analysis.document_likeness_score,
                "recapture_risk": analysis.recapture_risk_score,
                "tamper_risk": analysis.tamper_risk_score,
                "signals": "|".join(signal.code for signal in analysis.signals),
                "ocr_name": analysis.ocr.full_name or "",
                "passport_number": analysis.ocr.passport_number or "",
                "mrz_valid": str(analysis.ocr.mrz_valid),
            }
        )

    output = Path(args.csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    total = len(rows)
    genuine_total = counts["true_accept"] + counts["false_reject"]
    fraud_total = counts["true_reject"] + counts["false_accept"]
    correct = counts["true_accept"] + counts["true_reject"]
    false_reject_rate = counts["false_reject"] / max(genuine_total, 1)
    false_accept_rate = counts["false_accept"] / max(fraud_total, 1)
    fraud_precision = counts["true_reject"] / max(counts["true_reject"] + counts["false_reject"], 1)
    fraud_recall = counts["true_reject"] / max(fraud_total, 1)

    print(f"Dataset: {dataset_root}")
    print(f"Images: {total}")
    print(f"Accuracy: {percentage(correct / total)}")
    print(f"False reject rate: {percentage(false_reject_rate)} ({counts['false_reject']}/{genuine_total})")
    print(f"False accept rate: {percentage(false_accept_rate)} ({counts['false_accept']}/{fraud_total})")
    print(f"Fraud precision: {percentage(fraud_precision)}")
    print(f"Fraud recall: {percentage(fraud_recall)}")
    print()
    print("Per folder:")
    for folder, folder_counts in sorted(by_folder.items()):
        folder_accuracy = folder_counts["correct"] / max(folder_counts["total"], 1)
        print(
            f"  {folder:28} total={folder_counts['total']:4} "
            f"passed={folder_counts['passed']:4} rejected={folder_counts['rejected']:4} "
            f"accuracy={percentage(folder_accuracy)}"
        )
    print()
    print(f"Wrote CSV: {output}")

    if counts["false_reject"] or counts["false_accept"]:
        print()
        print("Mistakes:")
        for row in rows:
            if row["expected"] != row["predicted"]:
                print(f"  {row['path']} expected={row['expected']} predicted={row['predicted']} signals={row['signals']}")

    return_code = 1 if counts["false_reject"] or counts["false_accept"] else 0
    sys.exit(return_code)


if __name__ == "__main__":
    main()
