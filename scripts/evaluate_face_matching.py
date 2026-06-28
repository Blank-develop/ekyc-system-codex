"""Evaluate face-matching accuracy (selfie <-> document) — FAR / FRR / EER.

Measures how well the SFace embeddings + compare() separate genuine pairs
(same person) from impostor pairs (different people), and finds the threshold
that balances false-accept and false-reject. Use it to validate / tune
LALIGENCE_MIN_FACE_MATCH_SCORE (default 0.68) and the face-login threshold.

Expected dataset layout (one folder per identity):

    test_dataset/face_matching/
        person_001/
            reference.jpg      # the document portrait (or name it document*/id*/portrait*)
            selfie_1.jpg        # one or more live selfies of the SAME person
            selfie_2.jpg
        person_002/
            reference.jpg
            selfie_1.jpg
        ...

Run from the repo root:
    PYTHONPATH=backend .venv/bin/python scripts/evaluate_face_matching.py
"""

from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "test_dataset" / "face_matching"
OUT_DIR = ROOT / "outputs" / "face_matching_eval"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
REFERENCE_HINTS = ("reference", "document", "doc", "portrait", "id", "passport")
IMPOSTOR_SAMPLES_PER_IDENTITY = 8  # cap impostor pairs per identity to keep it fast


def image_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)


def split_reference_and_selfies(files: list[Path]) -> tuple[Path | None, list[Path]]:
    ref = next((f for f in files if any(h in f.name.lower() for h in REFERENCE_HINTS)), None)
    if ref is None and files:
        ref = files[0]
    selfies = [f for f in files if f != ref]
    return ref, selfies


def far_frr_at(genuine: list[float], impostor: list[float], threshold: float) -> tuple[float, float]:
    frr = sum(1 for s in genuine if s < threshold) / len(genuine) if genuine else 0.0
    far = sum(1 for s in impostor if s >= threshold) / len(impostor) if impostor else 0.0
    return far, frr


def main() -> int:
    sys.path.insert(0, str(ROOT / "backend"))
    from app.services.face_biometrics import OpenCvFaceRecognizer

    if not DATASET.exists() or not any(DATASET.iterdir()):
        print(f"No data in {DATASET}.")
        print("Create one folder per identity with a reference (document) image + selfies.")
        print("See the docstring / docs/dataset-collection-plan.md for the layout.")
        return 0

    recognizer = OpenCvFaceRecognizer()
    recognizer.warm_up()

    # 1. Load embeddings per identity.
    identities: dict[str, dict] = {}
    skipped: list[str] = []
    for folder in sorted(p for p in DATASET.iterdir() if p.is_dir()):
        files = image_files(folder)
        ref, selfies = split_reference_and_selfies(files)
        if ref is None or not selfies:
            skipped.append(f"{folder.name} (need a reference + >=1 selfie)")
            continue
        ref_emb = recognizer.extract(ref.read_bytes(), "match").embedding
        if ref_emb is None:
            skipped.append(f"{folder.name}/{ref.name} (no face in reference)")
            continue
        selfie_embs = []
        for s in selfies:
            emb = recognizer.extract(s.read_bytes(), "match").embedding
            if emb is None:
                skipped.append(f"{folder.name}/{s.name} (no face)")
                continue
            selfie_embs.append((s.name, emb))
        if not selfie_embs:
            continue
        identities[folder.name] = {"ref": ref_emb, "selfies": selfie_embs}

    if len(identities) < 1:
        print("No usable identities (need a detectable face in the reference and at least one selfie).")
        if skipped:
            print("Skipped:", *skipped, sep="\n  - ")
        return 0

    rows: list[dict] = []
    genuine_scores: list[float] = []
    impostor_scores: list[float] = []
    id_names = list(identities.keys())

    # 2. Genuine: reference vs own selfies.
    for name, data in identities.items():
        for selfie_name, emb in data["selfies"]:
            score = recognizer.compare(data["ref"], emb)
            genuine_scores.append(score)
            rows.append({"pair": "genuine", "ref_id": name, "selfie_id": name, "selfie": selfie_name, "score": round(score, 4)})

    # 3. Impostor: reference vs other identities' selfies (sampled).
    for name, data in identities.items():
        others = [o for o in id_names if o != name]
        random.shuffle(others)
        taken = 0
        for other in others:
            for selfie_name, emb in identities[other]["selfies"]:
                score = recognizer.compare(data["ref"], emb)
                impostor_scores.append(score)
                rows.append({"pair": "impostor", "ref_id": name, "selfie_id": other, "selfie": selfie_name, "score": round(score, 4)})
                taken += 1
                if taken >= IMPOSTOR_SAMPLES_PER_IDENTITY:
                    break
            if taken >= IMPOSTOR_SAMPLES_PER_IDENTITY:
                break

    # 4. Threshold sweep + EER.
    sweep = []
    best_eer = None
    for i in range(20, 96, 2):
        t = i / 100
        far, frr = far_frr_at(genuine_scores, impostor_scores, t)
        sweep.append({"threshold": t, "far": round(far, 4), "frr": round(frr, 4)})
        if best_eer is None or abs(far - frr) < abs(best_eer["far"] - best_eer["frr"]):
            best_eer = {"threshold": t, "far": far, "frr": frr}

    current = {}
    for label, t in (("min_face_match_score(0.68)", 0.68), ("face_login_threshold(0.72)", 0.72)):
        far, frr = far_frr_at(genuine_scores, impostor_scores, t)
        current[label] = {"far": round(far, 4), "frr": round(frr, 4)}

    summary = {
        "identities": len(identities),
        "genuine_pairs": len(genuine_scores),
        "impostor_pairs": len(impostor_scores),
        "genuine_score_mean": round(sum(genuine_scores) / len(genuine_scores), 4) if genuine_scores else None,
        "impostor_score_mean": round(sum(impostor_scores) / len(impostor_scores), 4) if impostor_scores else None,
        "equal_error_rate_point": {k: round(v, 4) for k, v in best_eer.items()} if best_eer else None,
        "at_current_thresholds": current,
        "skipped": skipped,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "summary.json").write_text(json.dumps({"summary": summary, "threshold_sweep": sweep}, indent=2), encoding="utf-8")
    if rows:
        with (OUT_DIR / "pairs.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    print(json.dumps(summary, indent=2))
    print(f"\nCSV: {OUT_DIR / 'pairs.csv'}")
    print(f"Summary: {OUT_DIR / 'summary.json'}")
    print("\nReading it: FRR = genuine users wrongly rejected; FAR = impostors wrongly accepted.")
    print("Pick the threshold near the equal-error-rate point, or bias toward low FAR for stricter security.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
