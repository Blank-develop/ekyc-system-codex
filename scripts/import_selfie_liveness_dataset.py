from __future__ import annotations

import argparse
import csv
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_DIR = ROOT / "test_dataset" / "selfie_passive_liveness_face_login"
MEDIA_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
    ".mp4",
    ".mov",
    ".m4v",
    ".avi",
    ".mkv",
    ".webm",
}


@dataclass(frozen=True)
class ImportItem:
    source: Path
    label: str
    target: Path


def label_folders(dataset_dir: Path) -> list[str]:
    if not dataset_dir.exists():
        raise SystemExit(f"Dataset folder does not exist: {dataset_dir}")
    labels = sorted(path.name for path in dataset_dir.iterdir() if path.is_dir() and not path.name.startswith("."))
    if not labels:
        raise SystemExit(f"No label folders found in: {dataset_dir}")
    return labels


def media_files(source: Path) -> list[Path]:
    if source.is_file():
        return [source] if source.suffix.lower() in MEDIA_EXTENSIONS else []
    if source.is_dir():
        return sorted(path for path in source.rglob("*") if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS)
    return []


def unique_target_path(target_dir: Path, filename: str, overwrite: bool) -> Path:
    target = target_dir / filename
    if overwrite or not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    counter = 2
    while True:
        candidate = target_dir / f"{stem}_{counter:03d}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def build_single_label_items(
    sources: list[Path],
    label: str,
    dataset_dir: Path,
    overwrite: bool,
) -> list[ImportItem]:
    target_dir = dataset_dir / label
    items: list[ImportItem] = []
    for source in sources:
        for media in media_files(source):
            target = unique_target_path(target_dir, media.name, overwrite)
            items.append(ImportItem(source=media, label=label, target=target))
    return items


def build_labeled_root_items(
    source_root: Path,
    dataset_dir: Path,
    labels: list[str],
    overwrite: bool,
) -> list[ImportItem]:
    if not source_root.exists() or not source_root.is_dir():
        raise SystemExit(f"Labeled source root does not exist: {source_root}")
    label_set = set(labels)
    items: list[ImportItem] = []
    for source_label_dir in sorted(path for path in source_root.iterdir() if path.is_dir()):
        label = source_label_dir.name
        if label not in label_set:
            continue
        for media in media_files(source_label_dir):
            relative = media.relative_to(source_label_dir)
            safe_name = "_".join(relative.parts)
            target = unique_target_path(dataset_dir / label, safe_name, overwrite)
            items.append(ImportItem(source=media, label=label, target=target))
    return items


def write_manifest(dataset_dir: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        return
    manifest = dataset_dir / "import_manifest.csv"
    exists = manifest.exists()
    with manifest.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["imported_at", "label", "source", "target"])
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def import_items(items: list[ImportItem], move: bool, dry_run: bool) -> list[dict[str, str]]:
    imported_at = datetime.now().isoformat(timespec="seconds")
    rows: list[dict[str, str]] = []
    for item in items:
        print(f"{'MOVE' if move else 'COPY'} {item.source} -> {item.target}")
        if dry_run:
            continue
        item.target.parent.mkdir(parents=True, exist_ok=True)
        if move:
            shutil.move(str(item.source), str(item.target))
        else:
            shutil.copy2(item.source, item.target)
        rows.append(
            {
                "imported_at": imported_at,
                "label": item.label,
                "source": str(item.source),
                "target": str(item.target),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import local photos/videos into test_dataset/selfie_passive_liveness_face_login label folders."
    )
    parser.add_argument("sources", nargs="*", type=Path, help="Files or folders to import into --label.")
    parser.add_argument("--label", help="Target label folder, e.g. fake_printed_photo.")
    parser.add_argument("--labeled-root", type=Path, help="Source folder containing subfolders with the same names as dataset labels.")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--move", action="store_true", help="Move files instead of copying them.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite files with the same name.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned imports without copying or moving.")
    parser.add_argument("--list-labels", action="store_true", help="Show available target labels and exit.")
    args = parser.parse_args()

    dataset_dir = args.dataset_dir.expanduser().resolve()
    labels = label_folders(dataset_dir)

    if args.list_labels:
        print("\n".join(labels))
        return

    if args.label and args.labeled_root:
        raise SystemExit("Use either --label with sources, or --labeled-root, not both.")

    if args.label:
        if args.label not in labels:
            raise SystemExit(f"Unknown label {args.label!r}. Use --list-labels to see valid options.")
        if not args.sources:
            raise SystemExit("Provide at least one source file/folder when using --label.")
        sources = [path.expanduser().resolve() for path in args.sources]
        items = build_single_label_items(sources, args.label, dataset_dir, args.overwrite)
    elif args.labeled_root:
        items = build_labeled_root_items(args.labeled_root.expanduser().resolve(), dataset_dir, labels, args.overwrite)
    else:
        raise SystemExit("Use --label with source files/folders, or use --labeled-root.")

    if not items:
        raise SystemExit("No supported media files found to import.")

    rows = import_items(items, move=args.move, dry_run=args.dry_run)
    if not args.dry_run:
        write_manifest(dataset_dir, rows)

    action = "Would import" if args.dry_run else "Imported"
    print(f"{action} {len(items)} file(s) into {dataset_dir}")


if __name__ == "__main__":
    main()
