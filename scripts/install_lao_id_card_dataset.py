from __future__ import annotations

import argparse
import json
import os
import shutil
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = ROOT / "test_dataset" / "lao_id_card"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

ROBOFLOW_DATASETS = {
    "document": {
        "workspace": "id-card-lao",
        "project": "lao-id-card-detect",
        "version": 1,
        "target": "document_detection",
        "source_url": "https://universe.roboflow.com/id-card-lao/lao-id-card-detect",
        "description": "Lao ID card object detection dataset.",
    },
    "fields": {
        "workspace": "id-card-lao",
        "project": "lao-id-card-detect-field",
        "version": 1,
        "target": "field_detection",
        "source_url": "https://universe.roboflow.com/id-card-lao/lao-id-card-detect-field",
        "description": "Lao ID card field detection dataset for OCR/layout crops.",
    },
}


class RoboflowExportError(RuntimeError):
    def __init__(self, status_code: int | None, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def fetch_json(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise RoboflowExportError(exc.code, f"HTTP {exc.code} from Roboflow: {detail}") from exc
    return json.loads(payload)


def download_file(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_target = target.with_suffix(target.suffix + ".download")
    with urllib.request.urlopen(url) as response, temp_target.open("wb") as file:
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
    temp_target.replace(target)
    print()


def ensure_dirs() -> None:
    for folder in [
        "document_detection",
        "field_detection",
        "_downloads",
        "_sources",
    ]:
        (DATASET_ROOT / folder).mkdir(parents=True, exist_ok=True)


def roboflow_export_url(workspace: str, project: str, version: int, export_format: str, api_key: str) -> str:
    return (
        f"https://api.roboflow.com/{urllib.parse.quote(workspace)}/"
        f"{urllib.parse.quote(project)}/{version}/{urllib.parse.quote(export_format)}"
        f"?api_key={urllib.parse.quote(api_key)}"
    )


def resolve_download_link(dataset: dict[str, Any], version: int, export_format: str, api_key: str) -> str:
    export_url = roboflow_export_url(
        dataset["workspace"],
        dataset["project"],
        version,
        export_format,
        api_key,
    )
    try:
        payload = fetch_json(export_url)
    except RoboflowExportError as exc:
        project = dataset["project"]
        if exc.status_code == 401:
            raise SystemExit(
                f"Roboflow rejected the API key while exporting {project} v{version}.\n"
                "Check that ROBOFLOW_API_KEY is your real Roboflow private API key, not the masked API**** value, "
                "and that your Roboflow account can access this public Universe dataset.\n"
                f"Roboflow response: {exc}"
            ) from exc
        if exc.status_code == 404:
            raise SystemExit(
                f"Roboflow could not load {project} v{version} for API export.\n"
                "This usually means that version number was not generated/exported, the project slug changed, "
                "or the public Universe page is visible but dataset export is not permitted for your account.\n"
                f"Try probing versions: ROBOFLOW_API_KEY=your_key .venv/bin/python scripts/install_lao_id_card_dataset.py --probe-fields\n"
                f"Or download the ZIP manually from {dataset['source_url']} and import it with --import-field-zip /path/to/export.zip.\n"
                f"Roboflow response: {exc}"
            ) from exc
        raise SystemExit(
            f"Could not export {project} v{version} as {export_format}.\n"
            f"Roboflow response: {exc}"
        ) from exc
    link = payload.get("export", {}).get("link") or payload.get("link")
    if not link:
        raise RuntimeError(f"Roboflow did not return a download link for {dataset['project']}: {payload}")
    return str(link)


def probe_versions(name: str, export_format: str, api_key: str, max_version: int) -> None:
    dataset = ROBOFLOW_DATASETS[name]
    project = dataset["project"]
    print(f"Probing Roboflow versions for {project} ({export_format})...")
    found = []
    for version in range(1, max_version + 1):
        export_url = roboflow_export_url(dataset["workspace"], project, version, export_format, api_key)
        try:
            payload = fetch_json(export_url)
        except RoboflowExportError as exc:
            print(f"  v{version}: unavailable ({exc.status_code})")
            continue
        link = payload.get("export", {}).get("link") or payload.get("link")
        if link:
            found.append(version)
            print(f"  v{version}: available")
        else:
            print(f"  v{version}: response did not include a download link")
    if found:
        versions = ", ".join(str(version) for version in found)
        print(f"Available versions for {project}: {versions}")
    else:
        print(f"No downloadable versions found for {project} from v1 to v{max_version}.")


def import_zip(name: str, archive: Path, force: bool) -> None:
    dataset = ROBOFLOW_DATASETS[name]
    if not archive.exists():
        raise SystemExit(f"ZIP file does not exist: {archive}")
    target_dir = DATASET_ROOT / dataset["target"]
    if target_dir.exists() and force:
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    if count_images(target_dir) > 0 and not force:
        raise SystemExit(f"{target_dir} already contains images. Re-run with --force to replace it.")

    with zipfile.ZipFile(archive) as zip_file:
        zip_file.extractall(target_dir)

    source_record = {
        "name": name,
        "description": dataset["description"],
        "source_url": dataset["source_url"],
        "workspace": dataset["workspace"],
        "project": dataset["project"],
        "format": "manual_zip_import",
        "license_note": "Roboflow Universe page listed this dataset as CC BY 4.0 when reviewed.",
        "installed_to": str(target_dir.relative_to(ROOT)),
        "archive": str(archive),
    }
    source_path = DATASET_ROOT / "_sources" / f"{name}.json"
    source_path.write_text(json.dumps(source_record, indent=2) + "\n", encoding="utf-8")
    print(f"Imported {archive} to {target_dir}")


def install_dataset(name: str, version: int, export_format: str, api_key: str, force: bool) -> None:
    dataset = ROBOFLOW_DATASETS[name]
    target_dir = DATASET_ROOT / dataset["target"]
    archive = DATASET_ROOT / "_downloads" / f"{dataset['project']}_v{version}_{export_format}.zip"

    if target_dir.exists() and count_images(target_dir) > 0 and not force:
        print(f"Already installed: {target_dir} ({count_images(target_dir)} images)")
        return

    if target_dir.exists() and force:
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    print(f"Resolving Roboflow export for {dataset['project']} v{version} ({export_format})...")
    link = resolve_download_link(dataset, version, export_format, api_key)
    download_file(link, archive)

    with zipfile.ZipFile(archive) as zip_file:
        zip_file.extractall(target_dir)

    source_record = {
        "name": name,
        "description": dataset["description"],
        "source_url": dataset["source_url"],
        "workspace": dataset["workspace"],
        "project": dataset["project"],
        "version": version,
        "format": export_format,
        "license_note": "Roboflow Universe page listed this dataset as CC BY 4.0 when reviewed.",
        "installed_to": str(target_dir.relative_to(ROOT)),
        "archive": str(archive.relative_to(ROOT)),
    }
    source_path = DATASET_ROOT / "_sources" / f"{name}.json"
    source_path.write_text(json.dumps(source_record, indent=2) + "\n", encoding="utf-8")
    print(f"Installed {dataset['project']} to {target_dir}")


def count_images(path: Path) -> int:
    return sum(1 for item in path.rglob("*") if item.suffix.lower() in IMAGE_EXTENSIONS)


def write_readme() -> None:
    readme = DATASET_ROOT / "README.md"
    readme.write_text(
        """# Lao ID Card Roboflow Datasets

This folder stores Lao government ID card datasets from Roboflow Universe.

- `document_detection/`: Lao ID card object detection.
- `field_detection/`: Lao ID card field detection for OCR/layout crops.
- `_sources/`: source metadata for the installed datasets.
- `_downloads/`: original downloaded Roboflow ZIP exports.

Install both datasets with a Roboflow API key:

```bash
ROBOFLOW_API_KEY=your_key .venv/bin/python scripts/install_lao_id_card_dataset.py --all
```

The Roboflow Universe pages listed these datasets as CC BY 4.0 when reviewed.
Inspect samples before using them in demos because public ID datasets may include
personal information.
""",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Install Lao ID card datasets from Roboflow Universe.")
    parser.add_argument("--all", action="store_true", help="Install both document and field datasets.")
    parser.add_argument("--document", action="store_true", help="Install Lao ID card document detection dataset.")
    parser.add_argument("--fields", action="store_true", help="Install Lao ID card field detection dataset.")
    parser.add_argument("--api-key", default=os.getenv("ROBOFLOW_API_KEY"), help="Roboflow API key. Defaults to ROBOFLOW_API_KEY.")
    parser.add_argument("--format", default="yolov8", help="Roboflow export format, e.g. yolov8, coco, voc.")
    parser.add_argument("--document-version", type=int, default=ROBOFLOW_DATASETS["document"]["version"])
    parser.add_argument("--field-version", type=int, default=ROBOFLOW_DATASETS["fields"]["version"])
    parser.add_argument("--probe-document", action="store_true", help="Check which document dataset versions are exportable.")
    parser.add_argument("--probe-fields", action="store_true", help="Check which field dataset versions are exportable.")
    parser.add_argument("--max-probe-version", type=int, default=10, help="Highest Roboflow version to probe.")
    parser.add_argument("--import-document-zip", type=Path, help="Import a manually downloaded document dataset ZIP.")
    parser.add_argument("--import-field-zip", type=Path, help="Import a manually downloaded field dataset ZIP.")
    parser.add_argument("--force", action="store_true", help="Replace existing installed folders.")
    args = parser.parse_args()

    selected = []
    if args.all or args.document:
        selected.append(("document", args.document_version))
    if args.all or args.fields:
        selected.append(("fields", args.field_version))
    import_jobs = []
    if args.import_document_zip:
        import_jobs.append(("document", args.import_document_zip))
    if args.import_field_zip:
        import_jobs.append(("fields", args.import_field_zip))

    probe_jobs = []
    if args.probe_document:
        probe_jobs.append("document")
    if args.probe_fields:
        probe_jobs.append("fields")

    if not selected and not import_jobs and not probe_jobs:
        parser.error("Choose --all, --document, or --fields.")

    ensure_dirs()
    write_readme()

    for name, archive in import_jobs:
        import_zip(name, archive, args.force)

    if probe_jobs and not args.api_key:
        raise SystemExit(
            "Roboflow requires an API key to probe exports. Re-run with "
            "ROBOFLOW_API_KEY=your_key or --api-key your_key."
        )
    for name in probe_jobs:
        probe_versions(name, args.format, args.api_key, args.max_probe_version)

    if selected and not args.api_key:
        raise SystemExit(
            "Roboflow requires an API key for dataset export. Re-run with "
            "ROBOFLOW_API_KEY=your_key or --api-key your_key."
        )

    for name, version in selected:
        install_dataset(name, version, args.format, args.api_key, args.force)

    print("\nInstalled image counts:")
    for folder in ["document_detection", "field_detection"]:
        path = DATASET_ROOT / folder
        print(f"  {folder}: {count_images(path)} images")


if __name__ == "__main__":
    main()
