"""Evaluate active-liveness attack/live datasets through the full server-side pipeline.

Groups images into bursts of 3 consecutive frames (as the route does) and reports
whether each burst would be rejected by the active-liveness quality-spoof gate.

Usage (from backend/):
    python ../scripts/evaluate_active_liveness_dataset.py [folder_name ...]

If no folder names are given, all folders under test_dataset/active_liveness/ are run.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = ROOT / "test_dataset" / "active_liveness"
OUTPUT_DIR = ROOT / "outputs" / "active_liveness_eval"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

EXPECTED_LABEL: dict[str, str] = {
    "fake_printed_photo": "spoof",
    "fake_phone_screen_replay": "spoof",
    "fake_tablet_screen_replay": "spoof",
    "fake_laptop_screen_replay": "spoof",
    "fake_video_replay_closeup": "spoof",
    "fake_cutout_or_paper_mask": "spoof",
    "real_live_face": "live",
    "real_live_face_with_glasses": "live",
    "real_live_poor_lighting": "live",
}


def image_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS)


def bursts_of(files: list[Path], size: int = 3) -> list[list[Path]]:
    return [files[i : i + size] for i in range(0, len(files), size) if files[i : i + size]]


def evaluate_burst(
    burst: list[Path],
    face_recognizer,
    passive_spoof,
    quality_fn,
    has_strong_replay_fn,
) -> dict[str, object]:
    from app.api.routes import _float_check

    contents = [p.read_bytes() for p in burst]
    face_results = [face_recognizer.extract(content, "active_liveness") for content in contents]
    passive_results = [
        passive_spoof.analyze(content, face_result.face_box)
        for content, face_result in zip(contents, face_results)
    ]

    face_width_ratios = [
        (_float_check(r.checks, "active_liveness_face_box_width")
         / max(_float_check(r.checks, "active_liveness_image_width"), 1.0))
        for r in face_results
    ]
    model_risks = [_float_check(r.checks, "passive_spoof_model_risk") for r in passive_results]

    quality_signals, quality_diag = quality_fn(face_width_ratios, model_risks)

    risks = [r.risk for r in passive_results]
    strong_replay = any(has_strong_replay_fn(r.checks, r.risk) for r in passive_results)

    screen_frame_scores = [_float_check(r.checks, "passive_spoof_screen_frame_score") for r in passive_results]
    display_surface_scores = [_float_check(r.checks, "passive_spoof_display_surface_score") for r in passive_results]
    paper_photo_scores = [_float_check(r.checks, "passive_spoof_paper_photo_score") for r in passive_results]
    heuristic_risks = [_float_check(r.checks, "passive_spoof_heuristic_risk") for r in passive_results]

    display_like_frame_count = sum(
        1
        for ss, ds, ms, hs in zip(screen_frame_scores, display_surface_scores, model_risks, heuristic_risks)
        if (
            ss >= 0.45
            or (ds >= 0.58 and ss >= 0.28)
            or (ds >= 0.62 and ss >= 0.22 and ms >= 0.82 and hs >= 0.3)
        )
    )
    recurring_display = len(passive_results) >= 3 and display_like_frame_count / len(passive_results) >= 0.67
    strong_replay = strong_replay or recurring_display

    all_signals = [*quality_signals]
    if strong_replay:
        all_signals.append("ACTIVE_LIVENESS_REPLAY_DETECTED")

    high_signal_codes = {s.code if hasattr(s, "code") else s for s in all_signals if (
        (hasattr(s, "severity") and s.severity == "high") or isinstance(s, str)
    )}

    usable_face = sum(1 for r in face_results if r.embedding is not None)
    if usable_face == 0:
        high_signal_codes.add("ACTIVE_LIVENESS_FACE_NOT_FOUND")

    rejected = bool(high_signal_codes)

    return {
        "burst_files": [p.name for p in burst],
        "rejected": rejected,
        "high_signals": sorted(high_signal_codes),
        "max_risk": round(max(risks, default=0.0), 3),
        "mean_risk": round(sum(risks) / len(risks) if risks else 0.0, 3),
        "max_model_risk": round(max(model_risks, default=0.0), 3),
        "max_screen_frame": round(max(screen_frame_scores, default=0.0), 3),
        "max_display_surface": round(max(display_surface_scores, default=0.0), 3),
        "max_paper_photo": round(max(paper_photo_scores, default=0.0), 3),
        "face_width_ratios": [round(r, 3) for r in face_width_ratios],
        "strong_replay": strong_replay,
        "recurring_display": recurring_display,
        "small_face_count": quality_diag["active_liveness_small_face_count"],
        "model_high_count": quality_diag["active_liveness_model_high_count"],
        "model_spoof_recurring": quality_diag["active_liveness_model_spoof_recurring"],
    }


def folder_summary(folder_name: str, results: list[dict]) -> dict:
    expected = EXPECTED_LABEL.get(folder_name, "unknown")
    total = len(results)
    rejected_count = sum(1 for r in results if r["rejected"])
    accepted_count = total - rejected_count

    if expected == "spoof":
        true_positives = rejected_count
        false_negatives = accepted_count
        detection_rate = round(true_positives / total, 4) if total else 0.0
        false_accept_rate = round(false_negatives / total, 4) if total else 0.0
        return {
            "folder": folder_name,
            "expected": expected,
            "total_bursts": total,
            "detected_as_spoof": true_positives,
            "missed_as_live": false_negatives,
            "detection_rate": detection_rate,
            "false_accept_rate": false_accept_rate,
        }
    else:
        true_negatives = accepted_count
        false_positives = rejected_count
        pass_rate = round(true_negatives / total, 4) if total else 0.0
        false_reject_rate = round(false_positives / total, 4) if total else 0.0
        return {
            "folder": folder_name,
            "expected": expected,
            "total_bursts": total,
            "passed_as_live": true_negatives,
            "false_rejected": false_positives,
            "pass_rate": pass_rate,
            "false_reject_rate": false_reject_rate,
        }


def main() -> None:
    import sys

    sys.path.insert(0, str(ROOT / "backend"))
    from app.api.routes import _has_strong_active_replay_evidence, active_liveness_quality_spoof_signals
    from app.services.face_biometrics import OpenCvFaceRecognizer, PassiveSpoofAnalyzer

    face_recognizer = OpenCvFaceRecognizer()
    passive_spoof = PassiveSpoofAnalyzer()
    passive_spoof.warm_up()

    target_folders = sys.argv[1:] if len(sys.argv) > 1 else None
    folders = (
        [DATASET_ROOT / name for name in target_folders]
        if target_folders
        else sorted(DATASET_ROOT.iterdir())
    )
    folders = [f for f in folders if f.is_dir() and not f.name.startswith(".")]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict] = []
    summaries: list[dict] = []

    for folder in folders:
        files = image_files(folder)
        if not files:
            print(f"  [{folder.name}] no images — skip")
            continue

        bursts = bursts_of(files, size=3)
        print(f"\n[{folder.name}] {len(files)} images → {len(bursts)} bursts")

        folder_results = []
        for i, burst in enumerate(bursts):
            result = evaluate_burst(burst, face_recognizer, passive_spoof, active_liveness_quality_spoof_signals, _has_strong_active_replay_evidence)
            result["folder"] = folder.name
            result["burst_index"] = i
            folder_results.append(result)
            all_rows.append(result)

            label = "REJECTED" if result["rejected"] else "PASSED"
            signals = ",".join(result["high_signals"]) if result["high_signals"] else "—"
            fw = result["face_width_ratios"]
            print(f"  burst {i:2d}: {label:8s}  risk={result['max_risk']:.2f}  model={result['max_model_risk']:.2f}  screen={result['max_screen_frame']:.2f}  fw={fw}  signals={signals}")

        summary = folder_summary(folder.name, folder_results)
        summaries.append(summary)

        print(f"\n  Summary for [{folder.name}]:")
        print(f"  {json.dumps(summary, indent=4)}")

    # Write CSV
    if all_rows:
        csv_path = OUTPUT_DIR / "results.csv"
        flat_rows = []
        for row in all_rows:
            flat = {k: v for k, v in row.items() if not isinstance(v, list)}
            flat["burst_files"] = "|".join(row["burst_files"])
            flat["face_width_ratios"] = "|".join(str(x) for x in row["face_width_ratios"])
            flat["high_signals"] = "|".join(row["high_signals"])
            flat_rows.append(flat)
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(flat_rows[0].keys()))
            writer.writeheader()
            writer.writerows(flat_rows)
        print(f"\nCSV: {csv_path}")

    json_path = OUTPUT_DIR / "summary.json"
    json_path.write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    print(f"Summary: {json_path}")


if __name__ == "__main__":
    main()
