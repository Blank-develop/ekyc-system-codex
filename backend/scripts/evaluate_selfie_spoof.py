from __future__ import annotations

import argparse
import csv
from pathlib import Path

from app.services.face_biometrics import OpenCvFaceRecognizer, PassiveSpoofAnalyzer


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def expected_label(path: Path, dataset_root: Path) -> str:
    folder = path.relative_to(dataset_root).parts[0]
    return "live" if folder.startswith("live") else "spoof"


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
    parser = argparse.ArgumentParser(description="Evaluate passive selfie spoof detection folders.")
    parser.add_argument("--dataset", default="test_dataset/selfie_spoof", help="Dataset root.")
    parser.add_argument("--only-folder", help="Evaluate only one top-level folder.")
    parser.add_argument("--csv", default="test_dataset/selfie_spoof/evaluation_results.csv", help="CSV output path.")
    parser.add_argument("--threshold", type=float, default=0.5, help="Spoof risk threshold for spoof decision.")
    args = parser.parse_args()

    dataset_root = Path(args.dataset).resolve()
    images = collect_images(dataset_root, args.only_folder)
    if not images:
        raise SystemExit(f"No images found under {dataset_root}")

    face_recognizer = OpenCvFaceRecognizer()
    spoof_analyzer = PassiveSpoofAnalyzer()

    rows: list[dict[str, str | float | bool]] = []
    counts = {"true_live": 0, "false_reject": 0, "true_spoof": 0, "false_accept": 0}
    by_folder: dict[str, dict[str, int]] = {}

    for image_path in images:
        content = image_path.read_bytes()
        expected = expected_label(image_path, dataset_root)
        face_result = face_recognizer.extract(content, "selfie")
        passive_result = spoof_analyzer.analyze(content, face_result.face_box)
        signals = [*face_result.signals, *passive_result.signals]
        has_high_signal = any(signal.severity == "high" for signal in signals)
        predicted = (
            "spoof"
            if passive_result.risk >= args.threshold
            or not passive_result.passed
            or not face_result.face_detected
            or has_high_signal
            else "live"
        )

        folder = image_path.relative_to(dataset_root).parts[0]
        by_folder.setdefault(folder, {"total": 0, "correct": 0, "live": 0, "spoof": 0})
        by_folder[folder]["total"] += 1
        by_folder[folder][predicted] += 1

        if expected == "live" and predicted == "live":
            counts["true_live"] += 1
            by_folder[folder]["correct"] += 1
        elif expected == "live" and predicted == "spoof":
            counts["false_reject"] += 1
        elif expected == "spoof" and predicted == "spoof":
            counts["true_spoof"] += 1
            by_folder[folder]["correct"] += 1
        else:
            counts["false_accept"] += 1

        rows.append(
            {
                "path": str(image_path.relative_to(dataset_root)),
                "expected": expected,
                "predicted": predicted,
                "face_detected": face_result.face_detected,
                "face_confidence": face_result.face_confidence,
                "risk": passive_result.risk,
                "passed": passive_result.passed,
                "signals": "|".join(signal.code for signal in signals),
                "checks": passive_result.checks,
            }
        )

    output = Path(args.csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    total = len(rows)
    live_total = counts["true_live"] + counts["false_reject"]
    spoof_total = counts["true_spoof"] + counts["false_accept"]
    correct = counts["true_live"] + counts["true_spoof"]
    print(f"Dataset: {dataset_root}")
    print(f"Images: {total}")
    print(f"Passive spoof accuracy: {percentage(correct / total)}")
    print(f"False reject rate: {percentage(counts['false_reject'] / max(live_total, 1))} ({counts['false_reject']}/{live_total})")
    print(f"False accept rate: {percentage(counts['false_accept'] / max(spoof_total, 1))} ({counts['false_accept']}/{spoof_total})")
    print()
    print("Per folder:")
    for folder, folder_counts in sorted(by_folder.items()):
        folder_accuracy = folder_counts["correct"] / max(folder_counts["total"], 1)
        print(
            f"  {folder:24} total={folder_counts['total']:4} "
            f"live={folder_counts['live']:4} spoof={folder_counts['spoof']:4} "
            f"accuracy={percentage(folder_accuracy)}"
        )
    print()
    print(f"Wrote CSV: {output}")

    for row in rows:
        if row["expected"] != row["predicted"]:
            print(f"  mistake: {row['path']} expected={row['expected']} predicted={row['predicted']} signals={row['signals']}")


if __name__ == "__main__":
    main()
