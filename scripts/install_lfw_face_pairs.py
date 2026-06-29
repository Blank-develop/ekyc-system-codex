"""Install LFW (Labeled Faces in the Wild) identities for face-matching evaluation.

Downloads the "multifaces" LFW subset (people with >=2 images) from a Hugging
Face mirror and organises it as one folder per identity under
test_dataset/face_matching/, ready for scripts/evaluate_face_matching.py.

LFW is the standard face-verification benchmark. It validates the matching
ENGINE (SFace) — note it is unconstrained celebrity photos, not the exact
document-portrait <-> live-selfie scenario, so the real eKYC FRR still needs
genuine user pairs. See docs/dataset-collection-plan.md.

Usage (from repo root):
    .venv/bin/python scripts/install_lfw_face_pairs.py --max-identities 70 --max-images 4
"""

from __future__ import annotations

import argparse
import re
import shutil
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "test_dataset" / "face_matching"
CACHE = ROOT / "test_dataset" / "_downloads"
BASE = "https://huggingface.co/datasets/vilsonrodrigues/lfw/resolve/main"
ARCHIVES = ["lfw_multifaces-retrieval.zip", "lfw_multifaces-ingestion.zip"]


def download(name: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / name
    if target.exists() and target.stat().st_size > 0:
        print(f"cached: {target.name}")
        return target
    print(f"downloading {name} ...")
    urllib.request.urlretrieve(f"{BASE}/{name}", target)
    return target


def main() -> int:
    ap = argparse.ArgumentParser(description="Install LFW identities for face-matching eval.")
    ap.add_argument("--max-identities", type=int, default=70)
    ap.add_argument("--max-images", type=int, default=4, help="images per identity (1 reference + selfies)")
    args = ap.parse_args()

    work = CACHE / "_lfw_extract"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    for name in ARCHIVES:
        archive = download(name)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(work)

    groups: dict[str, list[Path]] = defaultdict(list)
    for p in work.rglob("*.jpg"):
        m = re.match(r"(.+)_\d{4}$", p.stem)
        groups[m.group(1) if m else p.stem].append(p)

    usable = {k: v for k, v in groups.items() if len(v) >= 2}
    chosen = sorted(usable.items(), key=lambda kv: -len(kv[1]))[: args.max_identities]

    if DEST.exists():
        shutil.rmtree(DEST)
    total = 0
    for ident, files in chosen:
        files = sorted(files)[: args.max_images]
        d = DEST / ident
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy(files[0], d / "reference.jpg")
        for i, f in enumerate(files[1:], 1):
            shutil.copy(f, d / f"selfie_{i}.jpg")
        total += len(files)

    shutil.rmtree(work, ignore_errors=True)
    print(f"identities with >=2 images available: {len(usable)}")
    print(f"installed: {len(chosen)} identities, {total} images -> {DEST}")
    print("next: PYTHONPATH=backend .venv/bin/python scripts/evaluate_face_matching.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
