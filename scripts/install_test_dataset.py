from __future__ import annotations

import argparse
import shutil
import tarfile
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = ROOT / "test_dataset"
LOCAL_CASE_ROOT = Path("/Users/chilanhouthnitvongkhay/Desktop/ekyc-system-laligence/test_case")
REAL_PASSPORT_SAMPLE = Path("/Users/chilanhouthnitvongkhay/Desktop/Screenshot 2026-05-01 at 16.36.00.png")

IDNET_2025_FILES = {
    "EST": ("EST.tar.gz", 1_354_221_557),
    "FIN": ("FIN.tar.gz", 2_563_107_018),
    "ESP": ("ESP.tar.gz", 2_943_911_338),
    "RUS": ("RUS.tar.gz", 3_543_945_652),
    "GRC": ("GRC.tar.gz", 3_746_296_622),
    "AZE": ("AZE.tar.gz", 6_459_732_595),
    "LVA": ("LVA.tar.gz", 10_121_612_682),
    "SRB": ("SRB.tar.gz", 14_438_979_994),
}

CLASS_DIRS = {
    "genuine": "genuine",
    "positive": "genuine",
    "fraud5_inpaint_and_rewrite": "fraud_text_or_field_edit",
    "fraud6_crop_and_replace": "fraud_crop_replace",
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MIDV_IMAGE_EXTENSIONS = IMAGE_EXTENSIONS | {".bmp", ".tif", ".tiff"}
MIDV_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}
MIDV_2020_PASSPORT_TYPES = {
    "aze_passport",
    "grc_passport",
    "lva_passport",
    "srb_passport",
}


def ensure_dirs() -> None:
    for folder in [
        "genuine",
        "genuine_midv2020_passport",
        "fraud_face_substitution",
        "fraud_text_overlay",
        "fraud_text_or_field_edit",
        "fraud_crop_replace",
        "fraud_expired",
        "fraud_quality_blur",
        "fraud_missing_fields",
        "_downloads",
        "_sources",
    ]:
        (DATASET_ROOT / folder).mkdir(parents=True, exist_ok=True)


def copy_images(source: Path, target: Path) -> int:
    if not source.exists():
        return 0
    target.mkdir(parents=True, exist_ok=True)
    copied = 0
    for path in sorted(source.iterdir()):
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        shutil.copy2(path, target / path.name)
        copied += 1
    return copied


def seed_local() -> None:
    ensure_dirs()
    if REAL_PASSPORT_SAMPLE.exists():
        shutil.copy2(REAL_PASSPORT_SAMPLE, DATASET_ROOT / "genuine" / "savath_real_passport.png")

    mapping = [
        (LOCAL_CASE_ROOT / "Photo substitution ", DATASET_ROOT / "fraud_face_substitution"),
        (LOCAL_CASE_ROOT / "text_overlay", DATASET_ROOT / "fraud_text_overlay"),
        (LOCAL_CASE_ROOT / "ExpiryDate", DATASET_ROOT / "fraud_expired"),
        (LOCAL_CASE_ROOT / "blur", DATASET_ROOT / "fraud_quality_blur"),
    ]
    for source, target in mapping:
        copy_images(source, target)

    for filename in ["remove_somePart.png", "missing_fields.png"]:
        source = LOCAL_CASE_ROOT / filename
        if source.exists():
            shutil.copy2(source, DATASET_ROOT / "fraud_missing_fields" / filename)


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response, target.open("wb") as file:
        total = int(response.headers.get("content-length") or 0)
        downloaded = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            file.write(chunk)
            downloaded += len(chunk)
            if total:
                percent = downloaded / total * 100
                print(f"\rDownloading {target.name}: {percent:5.1f}%", end="", flush=True)
    print()


def download_idnet2025(location: str, yes_large_download: bool) -> Path:
    location = location.upper()
    if location not in IDNET_2025_FILES:
        options = ", ".join(sorted(IDNET_2025_FILES))
        raise SystemExit(f"Unknown IDNet-2025 location {location!r}. Choose one of: {options}")

    filename, size = IDNET_2025_FILES[location]
    gb = size / 1_000_000_000
    if not yes_large_download:
        raise SystemExit(
            f"{filename} is about {gb:.1f} GB. Re-run with --yes-large-download "
            "when you intentionally want to download it."
        )

    target = DATASET_ROOT / "_downloads" / filename
    if target.exists() and target.stat().st_size > 0:
        print(f"Already downloaded: {target}")
        return target

    url = f"https://huggingface.co/datasets/cactuslab/IDNet-2025/resolve/main/{filename}"
    download(url, target)
    return target


def extract_idnet2025(archive: Path, max_per_class: int) -> None:
    ensure_dirs()
    counters = {target: 0 for target in set(CLASS_DIRS.values())}
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            suffix = Path(member.name).suffix.lower()
            if suffix not in IMAGE_EXTENSIONS:
                continue

            target_class = None
            for marker, folder in CLASS_DIRS.items():
                if f"/{marker}/" in member.name or member.name.startswith(f"{marker}/"):
                    target_class = folder
                    break
            if target_class is None or counters[target_class] >= max_per_class:
                continue

            source = tar.extractfile(member)
            if source is None:
                continue
            output = DATASET_ROOT / target_class / f"idnet2025_{archive.stem}_{Path(member.name).name}"
            with output.open("wb") as file:
                shutil.copyfileobj(source, file)
            counters[target_class] += 1

            if all(count >= max_per_class for count in counters.values()):
                break

    print("Extracted IDNet-2025 samples:")
    for folder, count in sorted(counters.items()):
        print(f"  {folder}: {count}")


def list_idnet2025() -> None:
    print("IDNet-2025 public archives:")
    for location, (filename, size) in sorted(IDNET_2025_FILES.items(), key=lambda item: item[1][1]):
        print(f"  {location:3}  {filename:18}  {size / 1_000_000_000:5.1f} GB")


def _is_midv2020_passport_path(path: Path) -> bool:
    normalized = str(path).lower().replace("-", "_")
    return any(document_type in normalized for document_type in MIDV_2020_PASSPORT_TYPES)


def _midv2020_image_candidates(source_root: Path) -> list[Path]:
    return sorted(
        path
        for path in source_root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in MIDV_IMAGE_EXTENSIONS
        and _is_midv2020_passport_path(path)
        and not any(marker in path.name.lower() for marker in ("mask", "segm", "markup", "groundtruth", "annotation"))
    )


def _midv2020_video_candidates(source_root: Path) -> list[Path]:
    return sorted(
        path
        for path in source_root.rglob("*")
        if path.is_file() and path.suffix.lower() in MIDV_VIDEO_EXTENSIONS and _is_midv2020_passport_path(path)
    )


def _copy_midv2020_images(source_root: Path, max_per_type: int) -> dict[str, int]:
    target_root = DATASET_ROOT / "genuine_midv2020_passport"
    target_root.mkdir(parents=True, exist_ok=True)
    counters = {document_type: 0 for document_type in MIDV_2020_PASSPORT_TYPES}
    for path in _midv2020_image_candidates(source_root):
        normalized = str(path).lower().replace("-", "_")
        document_type = next((item for item in MIDV_2020_PASSPORT_TYPES if item in normalized), None)
        if document_type is None or counters[document_type] >= max_per_type:
            continue
        relative = path.relative_to(source_root)
        safe_name = "_".join(relative.parts)
        output = target_root / f"midv2020_{safe_name}"
        shutil.copy2(path, output)
        counters[document_type] += 1
        if all(count >= max_per_type for count in counters.values()):
            break
    return counters


def _extract_midv2020_video_frames(source_root: Path, max_per_type: int, frames_per_video: int) -> dict[str, int]:
    try:
        import cv2
    except ImportError:
        print("OpenCV is not installed; skipping MIDV-2020 video frame extraction.")
        return {document_type: 0 for document_type in MIDV_2020_PASSPORT_TYPES}

    target_root = DATASET_ROOT / "genuine_midv2020_passport"
    target_root.mkdir(parents=True, exist_ok=True)
    counters = {document_type: 0 for document_type in MIDV_2020_PASSPORT_TYPES}
    for path in _midv2020_video_candidates(source_root):
        normalized = str(path).lower().replace("-", "_")
        document_type = next((item for item in MIDV_2020_PASSPORT_TYPES if item in normalized), None)
        if document_type is None or counters[document_type] >= max_per_type:
            continue
        capture = cv2.VideoCapture(str(path))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if frame_count <= 0:
            capture.release()
            continue
        indexes = sorted({int(frame_count * ratio / (frames_per_video + 1)) for ratio in range(1, frames_per_video + 1)})
        for index in indexes:
            if counters[document_type] >= max_per_type:
                break
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = capture.read()
            if not ok:
                continue
            relative = path.relative_to(source_root)
            safe_name = "_".join(relative.with_suffix("").parts)
            output = target_root / f"midv2020_{safe_name}_frame{index}.jpg"
            cv2.imwrite(str(output), frame)
            counters[document_type] += 1
        capture.release()
        if all(count >= max_per_type for count in counters.values()):
            break
    return counters


def prepare_midv2020(source_root: Path, max_per_type: int, extract_video_frames: bool, frames_per_video: int) -> None:
    ensure_dirs()
    if not source_root.exists():
        raise SystemExit(f"MIDV-2020 folder does not exist: {source_root}")

    image_counts = _copy_midv2020_images(source_root, max_per_type)
    video_counts = {document_type: 0 for document_type in MIDV_2020_PASSPORT_TYPES}
    if extract_video_frames:
        remaining = max(max_per_type - count for count in image_counts.values())
        if remaining > 0:
            video_counts = _extract_midv2020_video_frames(source_root, max_per_type, frames_per_video)

    print("Prepared MIDV-2020 passport samples:")
    for document_type in sorted(MIDV_2020_PASSPORT_TYPES):
        total = image_counts.get(document_type, 0) + video_counts.get(document_type, 0)
        print(f"  {document_type:14} images={image_counts.get(document_type, 0):4} video_frames={video_counts.get(document_type, 0):4} total={total:4}")
    print(f"Output: {DATASET_ROOT / 'genuine_midv2020_passport'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Install or prepare LALIGENCE eKYC fraud test data.")
    parser.add_argument("--seed-local", action="store_true", help="Copy the local labeled test cases into test_dataset.")
    parser.add_argument("--list-idnet2025", action="store_true", help="Show known IDNet-2025 archive sizes.")
    parser.add_argument("--download-idnet2025", metavar="LOC", help="Download an IDNet-2025 archive, e.g. EST, GRC, AZE.")
    parser.add_argument("--prepare-midv2020", metavar="DIR", help="Copy passport samples from an extracted MIDV-2020 folder.")
    parser.add_argument("--midv2020-video-frames", action="store_true", help="Also extract sampled frames from MIDV-2020 videos.")
    parser.add_argument("--frames-per-video", type=int, default=2, help="Number of frames to sample from each MIDV-2020 video.")
    parser.add_argument("--extract", action="store_true", help="Extract sampled images from the downloaded archive.")
    parser.add_argument("--max-per-class", type=int, default=50, help="Maximum images to extract per class.")
    parser.add_argument("--yes-large-download", action="store_true", help="Required for multi-GB public archive downloads.")
    args = parser.parse_args()

    ensure_dirs()

    if args.seed_local:
        seed_local()
    if args.list_idnet2025:
        list_idnet2025()
    if args.download_idnet2025:
        archive = download_idnet2025(args.download_idnet2025, args.yes_large_download)
        if args.extract:
            extract_idnet2025(archive, args.max_per_class)
    if args.prepare_midv2020:
        prepare_midv2020(Path(args.prepare_midv2020).expanduser().resolve(), args.max_per_class, args.midv2020_video_frames, args.frames_per_video)

    if not any([args.seed_local, args.list_idnet2025, args.download_idnet2025, args.prepare_midv2020]):
        parser.print_help()


if __name__ == "__main__":
    main()
