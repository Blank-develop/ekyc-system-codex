from __future__ import annotations

import argparse
import csv
import mimetypes
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


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


def upload_document(client: TestClient, image_path: Path) -> dict:
    session = client.post("/api/verifications", json={"user_id": f"benchmark-{image_path.stem[:48]}"})
    session.raise_for_status()
    session_id = session.json()["session_id"]
    mime_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    with image_path.open("rb") as file:
        response = client.post(
            f"/api/verifications/{session_id}/document",
            files={"file": (image_path.name, file, mime_type)},
        )
    response.raise_for_status()
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the real FastAPI document upload route on a folder dataset.")
    parser.add_argument("--dataset", default="test_dataset", help="Dataset root with genuine*/ and fraud_* folders.")
    parser.add_argument("--only-folder", help="Evaluate only one top-level folder, e.g. genuine_midv2020_passport.")
    parser.add_argument("--csv", default="test_dataset/upload_evaluation_results.csv", help="CSV output path.")
    args = parser.parse_args()

    dataset_root = Path(args.dataset).resolve()
    images = collect_images(dataset_root, args.only_folder)
    if not images:
        detail = f" matching folder {args.only_folder!r}" if args.only_folder else ""
        raise SystemExit(f"No images found under {dataset_root}{detail}")

    client = TestClient(app)
    rows: list[dict[str, str | float]] = []
    counts = {"true_accept": 0, "false_reject": 0, "true_reject": 0, "false_accept": 0}
    by_folder: dict[str, dict[str, int]] = {}

    for image_path in images:
        label = expected_label(image_path, dataset_root)
        result = upload_document(client, image_path)
        document = result["document"]
        predicted = "fraud" if document["status"] == "rejected" else "genuine"
        folder = image_path.relative_to(dataset_root).parts[0]
        by_folder.setdefault(folder, {"total": 0, "correct": 0, "rejected": 0, "passed": 0})
        by_folder[folder]["total"] += 1
        by_folder[folder]["rejected" if document["status"] == "rejected" else "passed"] += 1

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
                "decision": result["decision"],
                "document_status": document["status"],
                "fraud_risk": document["fraud_risk_score"],
                "quality": document["image_quality_score"],
                "document_likeness": document["document_likeness_score"],
                "signals": "|".join(signal["code"] for signal in document["signals"]),
                "reason_codes": "|".join(result["reason_codes"]),
                "ocr_name": document["ocr"].get("full_name") or "",
                "passport_number": document["ocr"].get("passport_number") or "",
                "mrz_valid": str(document["ocr"].get("mrz_valid")),
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
    print(f"Dataset: {dataset_root}")
    print(f"Images: {total}")
    print(f"Upload accuracy: {percentage(correct / total)}")
    print(f"False reject rate: {percentage(counts['false_reject'] / max(genuine_total, 1))} ({counts['false_reject']}/{genuine_total})")
    print(f"False accept rate: {percentage(counts['false_accept'] / max(fraud_total, 1))} ({counts['false_accept']}/{fraud_total})")
    print()
    print("Per folder:")
    for folder, folder_counts in sorted(by_folder.items()):
        folder_accuracy = folder_counts["correct"] / max(folder_counts["total"], 1)
        print(
            f"  {folder:32} total={folder_counts['total']:4} "
            f"passed={folder_counts['passed']:4} rejected={folder_counts['rejected']:4} "
            f"accuracy={percentage(folder_accuracy)}"
        )
    print()
    print(f"Wrote CSV: {output}")

    for row in rows:
        if row["expected"] != row["predicted"]:
            print(f"  mistake: {row['path']} expected={row['expected']} predicted={row['predicted']} signals={row['signals']}")

    sys.exit(1 if counts["false_reject"] or counts["false_accept"] else 0)


if __name__ == "__main__":
    main()
