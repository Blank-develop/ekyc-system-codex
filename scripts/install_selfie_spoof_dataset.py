from __future__ import annotations

import argparse
import csv
import json
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = ROOT / "test_dataset" / "selfie_spoof"

DISPLAY_REPLAY_DATASET = "AxonData/Display_replay_attacks"
PRINT_PAPER_DATASET = "AxonData/print-cardboard-mask-face-spoofing"
AXON_LARGE_DATASET = "AxonData/face-anti-spoofing-dataset"
HF_ROWS_URL = "https://datasets-server.huggingface.co/rows"
HF_FIRST_ROWS_URL = "https://datasets-server.huggingface.co/first-rows"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mov", ".mp4", ".avi", ".mkv"}


def ensure_dirs() -> None:
    for folder in [
        "live_user_provided",
        "spoof_screen_replay",
        "spoof_print_paper",
        "spoof_mask_cutout",
        "spoof_unknown",
        "_downloads",
        "_sources",
    ]:
        (DATASET_ROOT / folder).mkdir(parents=True, exist_ok=True)


def fetch_rows(dataset: str, length: int, offset: int = 0) -> dict[str, Any]:
    urls = [
        (
            f"{HF_ROWS_URL}?dataset={urllib.parse.quote(dataset, safe='')}"
            f"&config=default&split=train&offset={offset}&length={length}"
        ),
        f"{HF_FIRST_ROWS_URL}?dataset={urllib.parse.quote(dataset, safe='')}&config=default&split=train",
    ]
    last_error: Exception | None = None
    for url in urls:
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=60) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    if "rows" in payload:
                        payload["rows"] = payload["rows"][offset : offset + length]
                    return payload
            except (urllib.error.URLError, urllib.error.HTTPError) as exc:
                last_error = exc
                time.sleep(1.4 * (attempt + 1))
    raise RuntimeError(f"Could not fetch Hugging Face dataset rows for {dataset}: {last_error}")


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 0:
        return

    safe_url = urllib.parse.quote(url, safe=":/?&=%")
    with urllib.request.urlopen(safe_url, timeout=120) as response, target.open("wb") as file:
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
    print(f"\rDownloaded {target.name} ({target.stat().st_size / 1_000_000:.1f} MB)")


def install_display_replay(max_images: int) -> list[dict[str, str]]:
    rows = fetch_rows(DISPLAY_REPLAY_DATASET, max_images)
    manifest: list[dict[str, str]] = []
    for item in rows.get("rows", []):
        row_idx = item["row_idx"]
        image = item["row"]["image"]
        target = DATASET_ROOT / "spoof_screen_replay" / f"axon_display_replay_{row_idx:03}.jpg"
        download(image["src"], target)
        manifest.append(
            {
                "path": str(target.relative_to(ROOT)),
                "expected": "spoof",
                "attack_type": "screen_replay",
                "source": DISPLAY_REPLAY_DATASET,
            }
        )
    return manifest


def extract_video_frames(video_path: Path, output_dir: Path, prefix: str, frames_per_video: int) -> list[Path]:
    try:
        import cv2
    except ImportError as exc:
        raise SystemExit("OpenCV is required to extract print/paper spoof video frames.") from exc

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if frame_count <= 0:
        positions = [0]
    else:
        positions = [int(frame_count * fraction) for fraction in evenly_spaced_fractions(frames_per_video)]

    outputs: list[Path] = []
    for frame_number, position in enumerate(positions):
        capture.set(cv2.CAP_PROP_POS_FRAMES, max(position, 0))
        ok, frame = capture.read()
        if not ok:
            continue
        output = output_dir / f"{prefix}_frame_{frame_number + 1:02}.jpg"
        cv2.imwrite(str(output), frame)
        outputs.append(output)
    capture.release()
    return outputs


def evenly_spaced_fractions(count: int) -> list[float]:
    if count <= 1:
        return [0.5]
    step = 0.6 / max(count - 1, 1)
    return [0.2 + step * index for index in range(count)]


def install_print_paper(max_videos: int, frames_per_video: int) -> list[dict[str, str]]:
    rows = fetch_rows(PRINT_PAPER_DATASET, max_videos)
    manifest: list[dict[str, str]] = []
    for item in rows.get("rows", []):
        row_idx = item["row_idx"]
        video = item["row"]["video"]
        video_path = DATASET_ROOT / "_downloads" / f"axon_print_paper_{row_idx:03}.mov"
        download(video["src"], video_path)
        outputs = extract_video_frames(
            video_path,
            DATASET_ROOT / "spoof_print_paper",
            f"axon_print_paper_{row_idx:03}",
            frames_per_video,
        )
        for output in outputs:
            manifest.append(
                {
                    "path": str(output.relative_to(ROOT)),
                    "expected": "spoof",
                    "attack_type": "print_paper_or_cardboard_mask",
                    "source": PRINT_PAPER_DATASET,
                }
            )
    return manifest


def fetch_all_rows(dataset: str, page_size: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        payload = fetch_rows(dataset, page_size, offset)
        page = payload.get("rows", [])
        rows.extend(page)
        total = int(payload.get("num_rows_total") or len(rows))
        if len(rows) >= total or not page:
            break
        offset += len(page)
    return rows


def classify_axon_large_video(src: str) -> tuple[str, str]:
    path = urllib.parse.unquote(urllib.parse.urlparse(src).path)
    parts = [part.strip() for part in path.split("/")]
    folder = "unknown"
    if "resolve" in parts:
        index = parts.index("resolve")
        if index + 2 < len(parts):
            folder = parts[index + 2]
    normalized = folder.lower().replace(" ", "_")
    if "replay" in normalized:
        return "spoof_screen_replay", normalized
    if "paper" in normalized:
        return "spoof_print_paper", normalized
    if any(marker in normalized for marker in ("cutout", "silicone", "latex", "textile", "mask")):
        return "spoof_mask_cutout", normalized
    return "spoof_unknown", normalized


def interleave_by_attack_type(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        folder, attack_type = classify_axon_large_video(row["row"]["video"]["src"])
        groups.setdefault(f"{folder}:{attack_type}", []).append(row)

    ordered: list[dict[str, Any]] = []
    while groups:
        for key in sorted(list(groups)):
            group = groups[key]
            if not group:
                del groups[key]
                continue
            ordered.append(group.pop(0))
    return ordered


def install_axon_large(target_images: int, frames_per_video: int, keep_videos: bool) -> list[dict[str, str]]:
    rows = interleave_by_attack_type(fetch_all_rows(AXON_LARGE_DATASET))
    manifest: list[dict[str, str]] = []
    produced = len(list(DATASET_ROOT.glob("spoof_*/axon_large_*_frame_*.jpg")))
    if produced:
        print(f"Resuming Axon large install with {produced} existing extracted frames.")
    for item in rows:
        if produced >= target_images:
            break
        row_idx = item["row_idx"]
        src = item["row"]["video"]["src"]
        target_folder, attack_type = classify_axon_large_video(src)
        prefix = f"axon_large_{attack_type}_{row_idx:03}"
        existing_outputs = sorted((DATASET_ROOT / target_folder).glob(f"{prefix}_frame_*.jpg"))
        if existing_outputs:
            continue
        suffix = Path(urllib.parse.urlparse(src).path).suffix.lower() or ".mp4"
        video_path = DATASET_ROOT / "_downloads" / f"axon_large_{row_idx:03}{suffix}"
        download(src, video_path)

        remaining = target_images - produced
        frame_count = min(frames_per_video, remaining)
        outputs = extract_video_frames(
            video_path,
            DATASET_ROOT / target_folder,
            prefix,
            frame_count,
        )
        for output in outputs:
            manifest.append(
                {
                    "path": str(output.relative_to(ROOT)),
                    "expected": "spoof",
                    "attack_type": attack_type,
                    "source": AXON_LARGE_DATASET,
                }
            )
        produced += len(outputs)
        if not keep_videos:
            video_path.unlink(missing_ok=True)
    return manifest


def copy_local(source: Path, target_folder: str, expected: str, attack_type: str) -> list[dict[str, str]]:
    if not source.exists():
        return []
    target = DATASET_ROOT / target_folder
    target.mkdir(parents=True, exist_ok=True)
    paths = [source] if source.is_file() else sorted(path for path in source.rglob("*") if path.is_file())
    manifest: list[dict[str, str]] = []
    for path in paths:
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        output = target / path.name
        shutil.copy2(path, output)
        manifest.append(
            {
                "path": str(output.relative_to(ROOT)),
                "expected": expected,
                "attack_type": attack_type,
                "source": str(path),
            }
        )
    return manifest


def existing_dataset_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    folder_attack_types = {
        "live_user_provided": "live_selfie",
        "spoof_screen_replay": "screen_replay",
        "spoof_print_paper": "print_paper_or_cardboard_mask",
        "spoof_mask_cutout": "mask_or_cutout",
        "spoof_unknown": "unknown_spoof",
    }
    for folder, fallback_attack_type in folder_attack_types.items():
        root = DATASET_ROOT / folder
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            name = path.name
            source = "user_provided"
            attack_type = fallback_attack_type
            if name.startswith("axon_display_replay"):
                source = DISPLAY_REPLAY_DATASET
                attack_type = "screen_replay"
            elif name.startswith("axon_print_paper"):
                source = PRINT_PAPER_DATASET
                attack_type = "print_paper_or_cardboard_mask"
            elif name.startswith("axon_large_"):
                source = AXON_LARGE_DATASET
                attack_type = fallback_attack_type
            rows.append(
                {
                    "path": str(path.relative_to(ROOT)),
                    "expected": "live" if folder.startswith("live") else "spoof",
                    "attack_type": attack_type,
                    "source": source,
                }
            )
    return rows


def write_readme() -> None:
    readme = DATASET_ROOT / "README.md"
    readme.write_text(
        """# Selfie Spoof Test Dataset

This folder is for passive liveness / selfie anti-spoof testing.

Expected labels:

- `live_user_provided/`: genuine live selfie samples you capture yourself.
- `spoof_screen_replay/`: screen replay attacks, where a face is shown on a display.
- `spoof_print_paper/`: printed-photo, paper, or cardboard-mask attacks.
- `spoof_mask_cutout/`: mask and cutout attacks.
- `spoof_unknown/`: extra spoof samples that do not fit the folders above.

The installer intentionally downloads a small sample by default. Serious PAD
datasets are often license-gated or very large, so keep this folder out of git
and grow it with your own phone tests, printed-photo tests, and office lighting
conditions.
""",
        encoding="utf-8",
    )


def write_manifest(rows: list[dict[str, str]]) -> None:
    manifest = DATASET_ROOT / "manifest.csv"
    existing: dict[str, dict[str, str]] = {}
    if manifest.exists():
        with manifest.open(newline="", encoding="utf-8") as file:
            for row in csv.DictReader(file):
                existing[row["path"]] = row
    for row in rows:
        existing[row["path"]] = row
    with manifest.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["path", "expected", "attack_type", "source"])
        writer.writeheader()
        writer.writerows(sorted(existing.values(), key=lambda row: row["path"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Install a small selfie spoof test dataset.")
    parser.add_argument("--max-screen-images", type=int, default=5, help="Display replay images to download.")
    parser.add_argument("--max-paper-videos", type=int, default=1, help="Print/paper spoof videos to download.")
    parser.add_argument("--frames-per-paper-video", type=int, default=2, help="Frames to extract from each paper spoof video.")
    parser.add_argument("--live-source", type=Path, help="Optional local genuine selfie image/folder to copy.")
    parser.add_argument("--screen-source", type=Path, help="Optional local screen spoof image/folder to copy.")
    parser.add_argument("--paper-source", type=Path, help="Optional local paper spoof image/folder to copy.")
    parser.add_argument("--skip-public", action="store_true", help="Only create folders/copy local sources.")
    parser.add_argument("--target-axon-large-images", type=int, default=0, help="Extract this many images from AxonData/face-anti-spoofing-dataset videos.")
    parser.add_argument("--axon-large-frames-per-video", type=int, default=10, help="Frames to extract from each Axon large video.")
    parser.add_argument("--keep-axon-large-videos", action="store_true", help="Keep downloaded Axon large videos after frame extraction.")
    args = parser.parse_args()

    ensure_dirs()
    rows: list[dict[str, str]] = []

    if not args.skip_public:
        if args.max_screen_images > 0:
            rows.extend(install_display_replay(args.max_screen_images))
        if args.max_paper_videos > 0:
            rows.extend(install_print_paper(args.max_paper_videos, args.frames_per_paper_video))
        if args.target_axon_large_images > 0:
            rows.extend(
                install_axon_large(
                    args.target_axon_large_images,
                    args.axon_large_frames_per_video,
                    args.keep_axon_large_videos,
                )
            )

    if args.live_source:
        rows.extend(copy_local(args.live_source, "live_user_provided", "live", "live_selfie"))
    if args.screen_source:
        rows.extend(copy_local(args.screen_source, "spoof_screen_replay", "spoof", "screen_replay"))
    if args.paper_source:
        rows.extend(copy_local(args.paper_source, "spoof_print_paper", "spoof", "print_paper"))

    rows.extend(existing_dataset_rows())
    write_readme()
    write_manifest(rows)

    print(f"Installed selfie spoof dataset at {DATASET_ROOT}")
    print(f"New/updated samples: {len(rows)}")
    print(f"Manifest: {DATASET_ROOT / 'manifest.csv'}")


if __name__ == "__main__":
    main()
