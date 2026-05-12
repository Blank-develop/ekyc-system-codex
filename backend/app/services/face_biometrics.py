from __future__ import annotations

import math
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError

from app.core.config import get_settings
from app.models.schemas import FraudSignal


ROOT = Path(__file__).resolve().parents[3]
FACE_MODEL_DIR = ROOT / "backend" / "models" / "face"
YUNET_MODEL = FACE_MODEL_DIR / "face_detection_yunet_2023mar.onnx"
SFACE_MODEL = FACE_MODEL_DIR / "face_recognition_sface_2021dec.onnx"
ANTI_SPOOF_MODEL_DIR = ROOT / "backend" / "models" / "anti_spoof"
ANTI_SPOOF_MODELS = (
    ANTI_SPOOF_MODEL_DIR / "best_model_quantized.onnx",
    ANTI_SPOOF_MODEL_DIR / "MiniFASNetV2.onnx",
    ANTI_SPOOF_MODEL_DIR / "MiniFASNetV1SE.onnx",
)
SELFIE_MIN_FACE_CONFIDENCE = 0.82


def _clamp(value: float) -> float:
    return max(0.0, min(value, 1.0))


def _signal(code: str, label: str, severity: str, score: float) -> FraudSignal:
    return FraudSignal(code=code, label=label, severity=severity, score=round(_clamp(score), 2))


@dataclass
class FaceEmbeddingResult:
    embedding: list[float] | None
    face_detected: bool
    face_confidence: float
    face_box: tuple[int, int, int, int] | None
    checks: dict[str, float | int | str | bool | None] = field(default_factory=dict)
    signals: list[FraudSignal] = field(default_factory=list)


@dataclass
class PassiveSpoofResult:
    risk: float
    passed: bool
    checks: dict[str, float | int | str | bool | None] = field(default_factory=dict)
    signals: list[FraudSignal] = field(default_factory=list)


class OpenCvFaceRecognizer:
    """OpenCV YuNet + SFace adapter for local face verification."""

    def __init__(self, yunet_model: Path = YUNET_MODEL, sface_model: Path = SFACE_MODEL) -> None:
        self.yunet_model = yunet_model
        self.sface_model = sface_model
        self._cv2: Any | None = None
        self._detector: Any | None = None
        self._recognizer: Any | None = None
        self._load_error: str | None = None

    def extract(self, content: bytes, source: str) -> FaceEmbeddingResult:
        image = self._decode(content)
        if image is None:
            return FaceEmbeddingResult(
                embedding=None,
                face_detected=False,
                face_confidence=0.0,
                face_box=None,
                checks={f"{source}_face_model": "opencv_sface", f"{source}_face_error": "unreadable_image"},
                signals=[_signal(f"{source.upper()}_FACE_IMAGE_UNREADABLE", "Face image is not readable.", "high", 1.0)],
            )

        loaded = self._ensure_loaded()
        if loaded is not None:
            return FaceEmbeddingResult(
                embedding=None,
                face_detected=False,
                face_confidence=0.0,
                face_box=None,
                checks={f"{source}_face_model": "opencv_sface", f"{source}_face_error": loaded},
                signals=[_signal("FACE_MODEL_UNAVAILABLE", "OpenCV face recognition model is unavailable.", "high", 0.92)],
            )

        cv2 = self._cv2
        assert cv2 is not None and self._detector is not None and self._recognizer is not None
        frame = self._pil_to_bgr(image)
        height, width = frame.shape[:2]
        self._detector.setInputSize((width, height))
        _, faces = self._detector.detect(frame)
        if faces is None or len(faces) == 0:
            return FaceEmbeddingResult(
                embedding=None,
                face_detected=False,
                face_confidence=0.0,
                face_box=None,
                checks={
                    f"{source}_face_model": "opencv_sface",
                    f"{source}_face_detected": False,
                    f"{source}_image_width": width,
                    f"{source}_image_height": height,
                },
                signals=[_signal(f"{source.upper()}_FACE_NOT_FOUND", "No usable face was detected.", "high", 0.9)],
            )

        face = self._select_face(faces, width, height, source)
        face_count = self._usable_face_count(faces, width, height)
        face_confidence = float(face[-1])
        aligned = self._recognizer.alignCrop(frame, face)
        embedding = self._recognizer.feature(aligned).flatten()
        norm = float(math.sqrt(float((embedding * embedding).sum())))
        if norm > 0:
            embedding = embedding / norm
        x, y, w, h = [int(round(value)) for value in face[:4]]
        area_ratio = (w * h) / max(width * height, 1)
        signals: list[FraudSignal] = []
        if source == "selfie" and face_confidence < SELFIE_MIN_FACE_CONFIDENCE:
            signals.append(_signal("SELFIE_FACE_CONFIDENCE_LOW", "Detected face is not confident enough for human selfie verification.", "high", 0.86))
        if source == "selfie" and face_count > 1:
            signals.append(_signal("SELFIE_MULTIPLE_FACES", "Multiple faces detected in selfie frame; remove screens or other faces.", "high", 0.86))

        return FaceEmbeddingResult(
            embedding=[float(value) for value in embedding.tolist()],
            face_detected=True,
            face_confidence=round(face_confidence, 3),
            face_box=(x, y, w, h),
            checks={
                f"{source}_face_model": "opencv_yunet_sface",
                f"{source}_face_detected": True,
                f"{source}_face_count": face_count,
                f"{source}_face_confidence": round(face_confidence, 3),
                f"{source}_face_confidence_threshold": SELFIE_MIN_FACE_CONFIDENCE if source == "selfie" else None,
                f"{source}_face_box_x": x,
                f"{source}_face_box_y": y,
                f"{source}_face_box_width": w,
                f"{source}_face_box_height": h,
                f"{source}_face_area_ratio": round(area_ratio, 4),
                f"{source}_image_width": width,
                f"{source}_image_height": height,
            },
            signals=signals,
        )

    def compare(self, embedding_a: list[float] | None, embedding_b: list[float] | None) -> float:
        if not embedding_a or not embedding_b or len(embedding_a) != len(embedding_b):
            return 0.0
        dot = sum(a * b for a, b in zip(embedding_a, embedding_b))
        return round(_clamp((dot + 1) / 2), 4)

    def _ensure_loaded(self) -> str | None:
        if self._detector is not None and self._recognizer is not None:
            return None
        if not self.yunet_model.exists() or not self.sface_model.exists():
            return "OpenCV YuNet/SFace ONNX files are missing from backend/models/face"
        try:
            import cv2
        except ImportError:
            return "opencv-contrib-python-headless is not installed"

        try:
            self._cv2 = cv2
            self._detector = cv2.FaceDetectorYN.create(str(self.yunet_model), "", (320, 320), 0.75, 0.3, 5000)
            self._recognizer = cv2.FaceRecognizerSF.create(str(self.sface_model), "")
        except Exception as exc:
            self._load_error = str(exc)
            return f"OpenCV face models failed to load: {exc}"
        return None

    @staticmethod
    def _decode(content: bytes) -> Image.Image | None:
        try:
            return ImageOps.exif_transpose(Image.open(BytesIO(content))).convert("RGB")
        except (UnidentifiedImageError, OSError):
            return None

    @staticmethod
    def _pil_to_bgr(image: Image.Image) -> Any:
        import numpy as np
        import cv2

        rgb = np.asarray(image)
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    @staticmethod
    def _select_face(faces: Any, width: int, height: int, source: str) -> Any:
        center_x = width / 2
        center_y = height / 2

        def score(face: Any) -> float:
            x, y, w, h = [float(value) for value in face[:4]]
            confidence = float(face[-1])
            area = w * h / max(width * height, 1)
            face_cx = x + w / 2
            face_cy = y + h / 2
            center_penalty = math.sqrt(((face_cx - center_x) / width) ** 2 + ((face_cy - center_y) / height) ** 2)
            left_bonus = 0.12 if source == "document" and face_cx < width * 0.45 else 0.0
            return confidence * 0.55 + area * 5.5 - center_penalty * 0.25 + left_bonus

        return max(faces, key=score)

    @staticmethod
    def _usable_face_count(faces: Any, width: int, height: int) -> int:
        count = 0
        for face in faces:
            x, y, w, h = [float(value) for value in face[:4]]
            confidence = float(face[-1])
            area_ratio = (w * h) / max(width * height, 1)
            if confidence >= 0.72 and area_ratio >= 0.018 and x + w > 0 and y + h > 0 and x < width and y < height:
                count += 1
        return count


class PassiveSpoofAnalyzer:
    """Passive screen/photo spoof risk.

    Runs the facenox MiniFAS ONNX classifier first when the model asset is
    installed, keeps Silent-Face-Anti-Spoofing MiniFAS exports as companion
    signals, and backs them with local screen/phone replay heuristics.
    """

    def __init__(self, model_paths: tuple[Path, ...] = ANTI_SPOOF_MODELS) -> None:
        self.model_paths = model_paths
        self._models: list[OnnxAntiSpoofModel] | None = None

    def analyze(self, content: bytes, face_box: tuple[int, int, int, int] | None = None) -> PassiveSpoofResult:
        try:
            image = ImageOps.exif_transpose(Image.open(BytesIO(content))).convert("RGB")
        except UnidentifiedImageError:
            return PassiveSpoofResult(
                risk=1.0,
                passed=False,
                checks={"passive_spoof_model": "heuristic_pad_v1", "passive_spoof_error": "unreadable_image"},
                signals=[_signal("PASSIVE_SPOOF_IMAGE_UNREADABLE", "Selfie image is unreadable for passive liveness.", "high", 1.0)],
            )

        crop = self._face_crop(image, face_box)
        gray = ImageOps.grayscale(crop)
        stat = ImageStat.Stat(gray)
        brightness = stat.mean[0]
        contrast = stat.stddev[0]
        sharpness = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).mean[0]
        glare_ratio = self._glare_ratio(crop)
        saturation_extreme = self._saturation_extremes(crop)
        moire = self._moire_score(crop)
        screen_frame = self._screen_frame_score(image, face_box)
        model_result = self._model_spoof_result(image, face_box)
        flatness = _clamp((22 - contrast) / 22)

        heuristic_risk = _clamp(
            glare_ratio * 1.6
            + saturation_extreme * 1.2
            + moire * 0.38
            + screen_frame * 0.9
            + flatness * 0.22
            + (0.18 if brightness > 232 or brightness < 38 else 0.0)
            + (0.14 if sharpness < 2.2 else 0.0)
        )
        risk = max(heuristic_risk, model_result["risk"])

        signals: list[FraudSignal] = []
        if risk >= 0.62:
            signals.append(_signal("PASSIVE_SPOOF_RISK_HIGH", "Passive liveness indicates likely screen/photo replay.", "high", risk))
        elif risk >= 0.38:
            signals.append(_signal("PASSIVE_SPOOF_RISK_MEDIUM", "Passive liveness found possible screen/photo replay cues.", "medium", risk))
        if glare_ratio > 0.16:
            signals.append(_signal("SELFIE_SCREEN_GLARE", "Strong display-like glare detected in selfie.", "medium", glare_ratio))
        if moire > 0.6:
            signals.append(_signal("SELFIE_SCREEN_PATTERN", "Screen-like high-frequency pattern detected in selfie.", "medium", moire))
        if screen_frame >= 0.62:
            signals.append(_signal("SELFIE_PHONE_SCREEN_FRAME", "A phone or screen-like rectangle appears around the face.", "high", screen_frame))
        elif screen_frame >= 0.42:
            signals.append(_signal("SELFIE_POSSIBLE_SCREEN_FRAME", "A possible screen rectangle appears around the face.", "medium", screen_frame))
        if model_result["risk"] >= 0.72 and model_result["available_count"] > 0:
            signals.append(_signal("PAD_MODEL_SPOOF_HIGH", "Anti-spoofing model predicts screen/photo spoof risk.", "high", model_result["risk"]))
        elif model_result["risk"] >= 0.52 and model_result["available_count"] > 0:
            signals.append(_signal("PAD_MODEL_SPOOF_MEDIUM", "Anti-spoofing model predicts possible spoof risk.", "medium", model_result["risk"]))

        return PassiveSpoofResult(
            risk=round(risk, 3),
            passed=risk < 0.5 and screen_frame < 0.62 and model_result["risk"] < 0.72,
            checks={
                "passive_spoof_model": "facenox_minifas_onnx_ensemble" if model_result["available_count"] else "heuristic_pad_v1",
                "passive_spoof_risk": round(risk, 3),
                "passive_spoof_heuristic_risk": round(heuristic_risk, 3),
                "passive_spoof_model_risk": round(model_result["risk"], 3),
                "passive_spoof_model_available_count": model_result["available_count"],
                "passive_spoof_glare_ratio": round(glare_ratio, 4),
                "passive_spoof_saturation_extreme": round(saturation_extreme, 4),
                "passive_spoof_moire_score": round(moire, 3),
                "passive_spoof_screen_frame_score": round(screen_frame, 3),
                "passive_spoof_face_brightness": round(brightness, 2),
                "passive_spoof_face_contrast": round(contrast, 2),
                "passive_spoof_face_sharpness": round(sharpness, 2),
                **model_result["checks"],
            },
            signals=signals,
        )

    def _model_spoof_result(self, image: Image.Image, face_box: tuple[int, int, int, int] | None) -> dict[str, Any]:
        models = self._load_models()
        checks: dict[str, float | int | str | bool | None] = {}
        primary_scores: list[float] = []
        primary_confidences: list[float] = []
        companion_scores: list[float] = []
        companion_confidences: list[float] = []
        for model in models:
            result = model.predict(image, face_box)
            prefix = f"pad_model_{model.model_id}"
            checks[f"{prefix}_status"] = result["status"]
            checks[f"{prefix}_family"] = result["family"]
            checks[f"{prefix}_risk"] = round(result["risk"], 3)
            checks[f"{prefix}_real_probability"] = round(result["real_probability"], 3)
            checks[f"{prefix}_spoof_probability"] = round(result["spoof_probability"], 3)
            checks[f"{prefix}_confidence"] = round(result["confidence"], 3)
            if result["status"] == "available":
                if result["family"] == "facenox_minifas_v2_se":
                    primary_scores.append(result["risk"])
                    primary_confidences.append(max(result["confidence"], 0.1))
                else:
                    companion_scores.append(result["risk"])
                    companion_confidences.append(max(result["confidence"], 0.1))
        if not primary_scores and not companion_scores:
            return {"risk": 0.0, "available_count": 0, "checks": checks}

        primary_risk = self._weighted_model_risk(primary_scores, primary_confidences)
        companion_risk = self._weighted_model_risk(companion_scores, companion_confidences)
        if primary_scores:
            # facenox is the calibrated primary model. The older MiniFAS exports
            # are useful supporting signals, but alone they are prone to false
            # positives on glasses, shadows, and webcam compression.
            if primary_risk >= 0.72:
                risk = max(primary_risk, companion_risk * 0.75)
            elif primary_risk >= 0.45:
                risk = max(primary_risk, companion_risk * 0.55)
            else:
                risk = max(primary_risk, min(companion_risk * 0.28, 0.34))
        else:
            risk = companion_risk

        checks["passive_spoof_primary_model_risk"] = round(primary_risk, 3)
        checks["passive_spoof_companion_model_risk"] = round(companion_risk, 3)
        checks["passive_spoof_primary_model_available"] = bool(primary_scores)
        return {"risk": _clamp(risk), "available_count": len(primary_scores) + len(companion_scores), "checks": checks}

    @staticmethod
    def _weighted_model_risk(scores: list[float], confidences: list[float]) -> float:
        if not scores:
            return 0.0
        weighted = sum(score * conf for score, conf in zip(scores, confidences)) / sum(confidences)
        return _clamp(max(weighted, max(scores) * 0.9))

    def _load_models(self) -> list["OnnxAntiSpoofModel"]:
        if self._models is not None:
            return self._models
        settings = get_settings()
        paths = self.model_paths if settings.pad_enable_companion_models else self.model_paths[:1]
        self._models = [OnnxAntiSpoofModel(path) for path in paths if path.exists()]
        return self._models

    @staticmethod
    def _face_crop(image: Image.Image, face_box: tuple[int, int, int, int] | None) -> Image.Image:
        if face_box is None:
            width, height = image.size
            return image.crop((int(width * 0.2), int(height * 0.12), int(width * 0.8), int(height * 0.82)))
        x, y, w, h = face_box
        pad_x = int(w * 0.28)
        pad_y = int(h * 0.34)
        left = max(0, x - pad_x)
        top = max(0, y - pad_y)
        right = min(image.width, x + w + pad_x)
        bottom = min(image.height, y + h + pad_y)
        return image.crop((left, top, right, bottom))

    @staticmethod
    def _glare_ratio(image: Image.Image) -> float:
        hsv = image.convert("HSV").resize((220, max(1, round(220 / (image.width / max(image.height, 1))))))
        total = hsv.width * hsv.height
        glare = sum(1 for _, sat, val in hsv.getdata() if val >= 244 and sat <= 38)
        return glare / max(total, 1)

    @staticmethod
    def _saturation_extremes(image: Image.Image) -> float:
        hsv = image.convert("HSV").resize((220, max(1, round(220 / (image.width / max(image.height, 1))))))
        total = hsv.width * hsv.height
        extreme = sum(1 for _, sat, val in hsv.getdata() if sat > 225 or val < 10)
        return extreme / max(total, 1)

    @staticmethod
    def _moire_score(image: Image.Image) -> float:
        gray = ImageOps.grayscale(image).resize((260, max(1, round(260 / (image.width / max(image.height, 1))))))
        sharpened = gray.filter(ImageFilter.SHARPEN)
        residual = ImageChops.difference(sharpened, sharpened.filter(ImageFilter.GaussianBlur(1.1)))
        residual_stat = ImageStat.Stat(residual)
        edges = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).mean[0] / 255
        return _clamp((residual_stat.stddev[0] / 36) * 0.68 + edges * 0.32)

    @staticmethod
    def _screen_frame_score(image: Image.Image, face_box: tuple[int, int, int, int] | None) -> float:
        try:
            import cv2
            import numpy as np
        except ImportError:
            return 0.0

        width, height = image.size
        if face_box is None:
            face_cx = width / 2
            face_cy = height / 2
        else:
            x, y, w, h = face_box
            face_cx = x + w / 2
            face_cy = y + h / 2

        scale = 640 / max(width, height)
        resized = image.resize((max(1, int(width * scale)), max(1, int(height * scale))))
        rgb = np.asarray(resized)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(gray, 45, 135)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        scaled_face_cx = face_cx * scale
        scaled_face_cy = face_cy * scale
        image_area = resized.width * resized.height
        best = 0.0
        for contour in contours:
            perimeter = cv2.arcLength(contour, True)
            if perimeter <= 0:
                continue
            approx = cv2.approxPolyDP(contour, 0.035 * perimeter, True)
            if len(approx) != 4 or not cv2.isContourConvex(approx):
                continue
            area = abs(cv2.contourArea(approx))
            area_ratio = area / max(image_area, 1)
            if area_ratio < 0.12 or area_ratio > 0.92:
                continue
            x, y, w, h = cv2.boundingRect(approx)
            if not (x <= scaled_face_cx <= x + w and y <= scaled_face_cy <= y + h):
                continue
            aspect = w / max(h, 1)
            if not (0.42 <= aspect <= 2.45):
                continue
            rectangularity = area / max(w * h, 1)
            if rectangularity < 0.62:
                continue

            roi_edges = edges[y : y + h, x : x + w]
            edge_density = float((roi_edges > 0).mean()) if roi_edges.size else 0.0
            roi = rgb[y : y + h, x : x + w]
            border = PassiveSpoofAnalyzer._border_pixels(roi)
            border_dark = float((border < 55).mean()) if border.size else 0.0
            border_bright = float((border > 235).mean()) if border.size else 0.0
            border_score = max(border_dark, border_bright)
            size_score = _clamp((area_ratio - 0.12) / 0.38)
            score = _clamp(rectangularity * 0.35 + edge_density * 2.4 * 0.2 + border_score * 0.25 + size_score * 0.2)
            best = max(best, score)
        return best

    @staticmethod
    def _border_pixels(region: Any) -> Any:
        import numpy as np

        if region.size == 0:
            return np.asarray([])
        height, width = region.shape[:2]
        band = max(2, min(width, height) // 18)
        strips = [
            region[:band, :, :],
            region[-band:, :, :],
            region[:, :band, :],
            region[:, -band:, :],
        ]
        pixels = np.concatenate([strip.reshape(-1, 3) for strip in strips], axis=0)
        return pixels.mean(axis=1)


class OnnxAntiSpoofModel:
    def __init__(self, model_path: Path) -> None:
        self.model_path = model_path
        self.family = self._family_for(model_path)
        self.model_id = self._model_id_for(model_path)
        self._session: Any | None = None
        self._input_name: str | None = None
        self._input_size: int | None = None
        self._output_classes: int | None = None
        self._load_error: str | None = None

    def predict(self, image: Image.Image, face_box: tuple[int, int, int, int] | None) -> dict[str, float | str]:
        if not self._ensure_loaded():
            return self._empty("error")
        try:
            tensor = self._preprocess(image, face_box, self._input_size or 128)
            logits = self._session.run(None, {self._input_name: tensor})[0].reshape(-1)
            real_probability, spoof_probability, confidence = self._probabilities(logits)
            return {
                "status": "available",
                "family": self.family,
                "risk": float(spoof_probability),
                "real_probability": float(real_probability),
                "spoof_probability": float(spoof_probability),
                "confidence": float(confidence),
            }
        except Exception:
            return self._empty("error")

    def _ensure_loaded(self) -> bool:
        if self._session is not None:
            return True
        try:
            import onnxruntime as ort
        except ImportError:
            self._load_error = "onnxruntime_missing"
            return False
        try:
            session_options = ort.SessionOptions()
            session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            self._session = ort.InferenceSession(str(self.model_path), sess_options=session_options, providers=["CPUExecutionProvider"])
            input_info = self._session.get_inputs()[0]
            output_info = self._session.get_outputs()[0]
            self._input_name = input_info.name
            self._input_size = int(input_info.shape[-1])
            self._output_classes = int(output_info.shape[-1])
            return True
        except Exception as exc:
            self._load_error = str(exc)
            return False

    def _probabilities(self, logits: Any) -> tuple[float, float, float]:
        import numpy as np

        values = np.asarray(logits, dtype="float32").reshape(-1)
        shifted = values - float(values.max())
        exp = np.exp(shifted)
        probabilities = exp / max(float(exp.sum()), 1e-6)
        if probabilities.size == 2:
            real = float(probabilities[0])
            spoof = float(probabilities[1])
        elif probabilities.size == 3:
            real = float(probabilities[1])
            spoof = float(probabilities[0] + probabilities[2])
        else:
            real = 0.0
            spoof = 0.0
        confidence = abs(real - spoof)
        return real, spoof, confidence

    @staticmethod
    def _family_for(model_path: Path) -> str:
        if model_path.name == "best_model_quantized.onnx":
            return "facenox_minifas_v2_se"
        if model_path.stem.startswith("MiniFASNet"):
            return "silent_face_anti_spoofing_minifas"
        return "onnx_anti_spoof"

    @staticmethod
    def _model_id_for(model_path: Path) -> str:
        if model_path.name == "best_model_quantized.onnx":
            return "facenox_best_model_quantized"
        return model_path.stem

    @staticmethod
    def _preprocess(image: Image.Image, face_box: tuple[int, int, int, int] | None, input_size: int) -> Any:
        import cv2
        import numpy as np

        crop = PassiveSpoofAnalyzer._face_crop(image, face_box)
        img = np.asarray(crop.convert("RGB"))
        old_h, old_w = img.shape[:2]
        ratio = float(input_size) / max(old_h, old_w)
        scaled_h = max(1, int(old_h * ratio))
        scaled_w = max(1, int(old_w * ratio))
        interpolation = cv2.INTER_LANCZOS4 if ratio > 1.0 else cv2.INTER_AREA
        img = cv2.resize(img, (scaled_w, scaled_h), interpolation=interpolation)
        delta_w = input_size - scaled_w
        delta_h = input_size - scaled_h
        top = delta_h // 2
        bottom = delta_h - top
        left = delta_w // 2
        right = delta_w - left
        img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_REFLECT_101)
        tensor = img.transpose(2, 0, 1).astype("float32") / 255.0
        return tensor[None, ...]

    def _empty(self, status: str) -> dict[str, float | str]:
        return {
            "status": status,
            "family": self.family,
            "risk": 0.0,
            "real_probability": 0.0,
            "spoof_probability": 0.0,
            "confidence": 0.0,
        }
