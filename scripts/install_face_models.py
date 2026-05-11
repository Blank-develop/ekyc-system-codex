from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FACE_MODEL_DIR = ROOT / "backend" / "models" / "face"
ANTI_SPOOF_MODEL_DIR = ROOT / "backend" / "models" / "anti_spoof"


@dataclass(frozen=True)
class ModelAsset:
    filename: str
    url: str
    directory: Path
    min_size: int


MODELS = (
    ModelAsset(
        filename="face_detection_yunet_2023mar.onnx",
        url="https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        directory=FACE_MODEL_DIR,
        min_size=100_000,
    ),
    ModelAsset(
        filename="face_recognition_sface_2021dec.onnx",
        url="https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        directory=FACE_MODEL_DIR,
        min_size=1_000_000,
    ),
    ModelAsset(
        filename="best_model_quantized.onnx",
        url="https://raw.githubusercontent.com/facenox/face-antispoof-onnx/main/models/best_model_quantized.onnx",
        directory=ANTI_SPOOF_MODEL_DIR,
        min_size=500_000,
    ),
    ModelAsset(
        filename="facenox_detector_quantized.onnx",
        url="https://raw.githubusercontent.com/facenox/face-antispoof-onnx/main/models/detector_quantized.onnx",
        directory=ANTI_SPOOF_MODEL_DIR,
        min_size=100_000,
    ),
)


def download(url: str, target: Path) -> None:
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
                print(f"\r{target.name}: {downloaded / total * 100:5.1f}%", end="", flush=True)
    print()
    temp_target.replace(target)


def main() -> None:
    for model in MODELS:
        target = model.directory / model.filename
        if target.exists() and target.stat().st_size >= model.min_size:
            print(f"Already installed: {target}")
            continue
        print(f"Downloading {model.filename}")
        download(model.url, target)


if __name__ == "__main__":
    main()
