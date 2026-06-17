from __future__ import annotations

import math
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import date
from io import BytesIO
from statistics import mean
from typing import Any

from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError

from app.core.config import get_settings
from app.models.schemas import DocumentAnalysis, FraudSignal, OcrResult
from app.services.document_models import DocumentFraudModelEnsemble, DocumentModelEnsembleResult, DocumentModelInput


SUPPORTED_IMAGE_TYPES = (".jpg", ".jpeg", ".png", ".webp")
MRZ_ALLOWED = re.compile(r"^[A-Z0-9<]{44}$")
MRZ_WEIGHTS = (7, 3, 1)
MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def _clamp(value: float) -> float:
    return max(0.0, min(value, 1.0))


def _signal(code: str, label: str, severity: str, score: float) -> FraudSignal:
    return FraudSignal(code=code, label=label, severity=severity, score=round(_clamp(score), 2))


@dataclass
class FraudContext:
    content: bytes
    filename: str
    image: Image.Image
    width: int
    height: int
    format: str | None
    exif_count: int
    checks: dict[str, float | int | str | bool | None] = field(default_factory=dict)
    signals: list[FraudSignal] = field(default_factory=list)

    @property
    def aspect(self) -> float:
        return self.width / max(self.height, 1)

    @property
    def pixels(self) -> int:
        return self.width * self.height


@dataclass
class QualityResult:
    score: float
    brightness: float
    contrast: float
    sharpness: float
    glare_ratio: float


@dataclass
class DocumentLikenessResult:
    score: float
    edge_density: float
    rectangularity: float


@dataclass
class ForensicResult:
    recapture_risk: float
    tamper_risk: float
    ela_score: float
    blockiness: float
    saturation_extreme_ratio: float


class OcrTextExtractor:
    def __init__(self) -> None:
        settings = get_settings()
        self.tesseract_path = shutil.which("tesseract")
        self.languages = self._available_languages()
        self.lao_id_ocr_engines = tuple(item.strip().lower() for item in settings.lao_id_ocr_engine.split(",") if item.strip())
        self.surya = SuryaOcrExtractor(enabled="surya" in self.lao_id_ocr_engines)

    def extract(self, context: FraudContext, document_type: str = "passport") -> str | None:
        if document_type == "lao_id_card" and "surya" in self.lao_id_ocr_engines:
            text = self.surya.extract(context)
            if text:
                context.checks["ocr_engine"] = "surya"
                context.checks["ocr_language"] = "lo+en"
                context.checks["ocr_text_chars"] = len(text)
                return text

        if document_type == "lao_id_card" and "tesseract" not in self.lao_id_ocr_engines:
            context.checks["ocr_engine"] = "unavailable"
            context.signals.append(_signal("OCR_ENGINE_UNAVAILABLE", "No Lao ID OCR engine produced readable text.", "low", 0.04))
            return None

        if not self.tesseract_path:
            context.checks["ocr_engine"] = "unavailable"
            context.signals.append(_signal("OCR_ENGINE_UNAVAILABLE", "Tesseract OCR is not available on this server.", "low", 0.04))
            return None

        try:
            import pytesseract
        except ImportError:
            context.checks["ocr_engine"] = "pytesseract_missing"
            context.signals.append(_signal("OCR_PACKAGE_UNAVAILABLE", "pytesseract is not installed in the backend environment.", "low", 0.04))
            return None

        context.checks["ocr_engine"] = "tesseract"
        text_blocks: list[str] = []
        config = "--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
        language = "eng"
        if document_type == "lao_id_card":
            config = "--oem 3 --psm 6"
            language = "lao+eng" if "lao" in self.languages else "eng"
        context.checks["ocr_language"] = language

        for name, image in self._ocr_regions(context.image):
            prepared = self._prepare_for_ocr(image)
            try:
                text = pytesseract.image_to_string(prepared, lang=language, config=config)
            except pytesseract.TesseractError as exc:
                context.checks["ocr_error"] = str(exc)
                continue
            if text.strip():
                context.checks[f"ocr_{name}_chars"] = len(text)
                text_blocks.append(text)

        if document_type == "passport":
            mrz_config = "--oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
            for name, image, psm in self._passport_mrz_regions(context.image):
                prepared = self._prepare_for_mrz_ocr(image)
                try:
                    text = pytesseract.image_to_string(prepared, lang="eng", config=f"{mrz_config} --psm {psm}")
                except pytesseract.TesseractError as exc:
                    context.checks["ocr_mrz_error"] = str(exc)
                    continue
                if text.strip():
                    context.checks[f"ocr_{name}_chars"] = len(text)
                    text_blocks.append(text)

        merged = "\n".join(text_blocks).strip()
        context.checks["ocr_text_chars"] = len(merged)
        if not merged:
            label = "OCR did not extract readable Lao ID card text." if document_type == "lao_id_card" else "OCR did not extract readable passport text."
            context.signals.append(_signal("OCR_TEXT_NOT_FOUND", label, "medium", 0.32))
            return None
        return merged

    def _available_languages(self) -> set[str]:
        if not self.tesseract_path:
            return set()
        try:
            result = subprocess.run(
                [self.tesseract_path, "--list-langs"],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (OSError, subprocess.SubprocessError):
            return set()
        output = "\n".join([result.stdout, result.stderr])
        return {line.strip() for line in output.splitlines() if line.strip() and not line.startswith("List of available")}

    @staticmethod
    def _ocr_regions(image: Image.Image) -> list[tuple[str, Image.Image]]:
        width, height = image.size
        return [
            ("full", image),
            ("bottom_45", image.crop((0, int(height * 0.55), width, height))),
            ("bottom_32", image.crop((0, int(height * 0.68), width, height))),
        ]

    @staticmethod
    def _passport_mrz_regions(image: Image.Image) -> list[tuple[str, Image.Image, int]]:
        width, height = image.size
        rotated_90 = image.rotate(90, expand=True)
        rotated_270 = image.rotate(270, expand=True)
        return [
            ("mrz_right_65_rot270", image.crop((int(width * 0.65), 0, width, height)).rotate(270, expand=True), 6),
            ("mrz_right_65_rot270_sparse", image.crop((int(width * 0.65), 0, width, height)).rotate(270, expand=True), 11),
            ("mrz_rot270_bottom_30", rotated_270.crop((0, int(rotated_270.height * 0.70), rotated_270.width, rotated_270.height)), 6),
            ("mrz_rot270_bottom_30_sparse", rotated_270.crop((0, int(rotated_270.height * 0.70), rotated_270.width, rotated_270.height)), 11),
            ("mrz_rot90_bottom_30", rotated_90.crop((0, int(rotated_90.height * 0.70), rotated_90.width, rotated_90.height)), 6),
        ]

    @staticmethod
    def _prepare_for_ocr(image: Image.Image) -> Image.Image:
        gray = ImageOps.grayscale(image)
        longest_side = max(gray.size)
        if longest_side < 1800:
            scale = math.ceil(1800 / longest_side)
            gray = gray.resize((gray.width * scale, gray.height * scale), Image.Resampling.LANCZOS)
        gray = ImageOps.autocontrast(gray)
        gray = gray.filter(ImageFilter.SHARPEN)
        return gray

    @staticmethod
    def _prepare_for_mrz_ocr(image: Image.Image) -> Image.Image:
        gray = OcrTextExtractor._prepare_for_ocr(image)
        try:
            import cv2
            import numpy as np
        except ImportError:
            return gray
        array = np.array(gray)
        blurred = cv2.GaussianBlur(array, (0, 0), 1.0)
        sharpened = cv2.addWeighted(array, 1.8, blurred, -0.8, 0)
        thresholded = cv2.adaptiveThreshold(
            sharpened,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            9,
        )
        return Image.fromarray(thresholded)


class SuryaOcrExtractor:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self._lock = threading.Lock()
        self._foundation_predictor: Any | None = None
        self._det_predictor: Any | None = None
        self._rec_predictor: Any | None = None
        self._task_name: str | None = None
        self._load_error: str | None = None

    def extract(self, context: FraudContext) -> str | None:
        if not self.enabled:
            return None
        try:
            self._ensure_loaded()
        except Exception as exc:
            self._load_error = self._trim_error(exc)
            context.checks["surya_ocr_available"] = False
            context.checks["surya_ocr_error"] = self._load_error
            return None
        if not self._rec_predictor or not self._det_predictor or not self._task_name:
            context.checks["surya_ocr_available"] = False
            if self._load_error:
                context.checks["surya_ocr_error"] = self._load_error
            return None

        image = self._prepare_image(context.image)
        try:
            predictions = self._rec_predictor(
                [image],
                task_names=[self._task_name],
                det_predictor=self._det_predictor,
                sort_lines=True,
                math_mode=False,
                return_words=False,
            )
        except Exception as exc:
            context.checks["surya_ocr_available"] = False
            context.checks["surya_ocr_error"] = self._trim_error(exc)
            return None

        lines: list[str] = []
        for prediction in predictions:
            for line in getattr(prediction, "text_lines", []):
                text = getattr(line, "text", "")
                if text and text.strip():
                    lines.append(text.strip())
        merged = "\n".join(lines).strip()
        context.checks["surya_ocr_available"] = True
        context.checks["surya_ocr_lines"] = len(lines)
        context.checks["surya_ocr_chars"] = len(merged)
        return merged or None

    def _ensure_loaded(self) -> None:
        if self._rec_predictor and self._det_predictor and self._task_name:
            return
        with self._lock:
            if self._rec_predictor and self._det_predictor and self._task_name:
                return
            from surya.common.surya.schema import TaskNames
            from surya.detection import DetectionPredictor
            from surya.foundation import FoundationPredictor
            from surya.recognition import RecognitionPredictor

            self._foundation_predictor = FoundationPredictor()
            self._det_predictor = DetectionPredictor()
            self._rec_predictor = RecognitionPredictor(self._foundation_predictor)
            self._task_name = TaskNames.ocr_with_boxes
            self._load_error = None

    @staticmethod
    def _prepare_image(image: Image.Image) -> Image.Image:
        rgb = image.convert("RGB")
        max_side = 1800
        if max(rgb.size) <= max_side:
            return rgb
        scale = max_side / max(rgb.size)
        size = (max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale)))
        return rgb.resize(size, Image.Resampling.LANCZOS)

    @staticmethod
    def _trim_error(exc: Exception) -> str:
        return f"{exc.__class__.__name__}: {exc}"[:240]


class ImageLoader:
    def load(self, content: bytes, filename: str) -> FraudContext | DocumentAnalysis:
        try:
            raw = Image.open(BytesIO(content))
            image_format = raw.format
            exif_count = len(raw.getexif() or {})
            image = ImageOps.exif_transpose(raw).convert("RGB")
        except UnidentifiedImageError:
            return DocumentAnalysis(
                status="rejected",
                image_quality_score=0.0,
                fraud_risk_score=1.0,
                document_likeness_score=0.0,
                recapture_risk_score=1.0,
                tamper_risk_score=1.0,
                signals=[_signal("NON_IMAGE_UPLOAD", "The uploaded file is not a readable passport image.", "high", 1.0)],
                checks={"filename": filename},
            )

        width, height = image.size
        context = FraudContext(
            content=content,
            filename=filename,
            image=image,
            width=width,
            height=height,
            format=image_format,
            exif_count=exif_count,
        )
        context.checks.update(
            {
                "filename": filename,
                "image_format": image_format,
                "width": width,
                "height": height,
                "megapixels": round(context.pixels / 1_000_000, 2),
                "aspect_ratio": round(context.aspect, 3),
                "exif_tags": exif_count,
                "file_size_kb": round(len(content) / 1024, 1),
            }
        )
        return context


class QualityAnalyzer:
    def analyze(self, context: FraudContext) -> QualityResult:
        gray = ImageOps.grayscale(context.image)
        stat = ImageStat.Stat(gray)
        brightness = stat.mean[0]
        contrast = stat.stddev[0]
        edges = gray.filter(ImageFilter.FIND_EDGES)
        sharpness = ImageStat.Stat(edges).mean[0]
        glare_ratio = self._glare_ratio(context.image, contrast)

        score = 0.28
        score += 0.22 if context.pixels >= 900_000 else 0.1 if context.pixels >= 450_000 else 0.0
        score += 0.18 if 65 <= brightness <= 215 else 0.04
        score += 0.18 if contrast >= 32 else 0.08 if contrast >= 20 else 0.0
        score += 0.16 if sharpness >= 12 else 0.07 if sharpness >= 7 else 0.0
        score += 0.08 if glare_ratio <= 0.08 else 0.0
        score = _clamp(score)

        context.checks.update(
            {
                "brightness": round(brightness, 2),
                "contrast": round(contrast, 2),
                "sharpness": round(sharpness, 2),
                "glare_ratio": round(glare_ratio, 4),
            }
        )

        if context.pixels < 350_000:
            context.signals.append(_signal("LOW_RESOLUTION", "Passport image resolution is too low for IAL2 evidence validation.", "high", 0.84))
        if (brightness < 45 or brightness > 238) and contrast < 32:
            context.signals.append(_signal("POOR_LIGHTING", "Image is too dark or overexposed for reliable inspection.", "medium", 0.5))
        if contrast < 20:
            context.signals.append(_signal("LOW_CONTRAST", "Low contrast may indicate glare, blur, photocopy, or screen recapture.", "medium", 0.48))
        if sharpness < 2.0:
            context.signals.append(_signal("BLUR_DETECTED", "Image is too blurry for reliable passport evidence validation.", "high", 0.78))
        elif sharpness < 5.0:
            context.signals.append(_signal("LOW_SHARPNESS", "Image sharpness is low; OCR and tamper localization may be less reliable.", "medium", 0.28))
        if glare_ratio > 0.12:
            context.signals.append(_signal("GLARE_OR_WASHOUT", "Large glare or washed-out areas were detected on the document image.", "medium", 0.54))

        lower_name = context.filename.lower()
        if not lower_name.endswith(SUPPORTED_IMAGE_TYPES):
            context.signals.append(_signal("UNSUPPORTED_FILE_TYPE", "Unsupported document file type.", "high", 0.9))

        return QualityResult(score=score, brightness=brightness, contrast=contrast, sharpness=sharpness, glare_ratio=glare_ratio)

    @staticmethod
    def _glare_ratio(image: Image.Image, contrast: float) -> float:
        hsv = image.convert("HSV")
        pixels = hsv.getdata()
        bright_low_sat = 0
        total = image.width * image.height
        for hue, sat, val in pixels:
            if val >= 242 and sat <= 34:
                bright_low_sat += 1
        bright_ratio = bright_low_sat / max(total, 1)
        # White document backgrounds are expected. Treat them as glare only when
        # the image also has weak contrast, which suggests washed-out evidence.
        if contrast >= 32:
            return min(bright_ratio, 0.08)
        return bright_ratio


class DocumentLikenessAnalyzer:
    def analyze(self, context: FraudContext) -> DocumentLikenessResult:
        gray = ImageOps.grayscale(context.image.resize((360, max(1, round(360 / context.aspect)))))
        edges = gray.filter(ImageFilter.FIND_EDGES)
        edge_stat = ImageStat.Stat(edges)
        edge_density = min(edge_stat.mean[0] / 42, 1.0)

        aspect_score = self._range_score(context.aspect, 0.62, 1.95)
        border_score = self._border_edge_score(edges)
        rectangularity = _clamp((aspect_score * 0.55) + (border_score * 0.45))
        score = _clamp((edge_density * 0.42) + (rectangularity * 0.58))

        context.checks.update(
            {
                "document_edge_density": round(edge_density, 3),
                "document_rectangularity": round(rectangularity, 3),
                "document_likeness": round(score, 3),
            }
        )

        if aspect_score < 0.45:
            context.signals.append(_signal("UNUSUAL_DOCUMENT_ASPECT", "Image shape does not resemble a passport/document capture.", "medium", 0.55))
        if score < 0.38:
            context.signals.append(_signal("NON_DOCUMENT_UPLOAD", "Image lacks expected document borders and text-like structure.", "high", 0.88))
        elif score < 0.55:
            context.signals.append(_signal("WEAK_DOCUMENT_STRUCTURE", "Document structure is weak; crop or background may be unreliable.", "medium", 0.5))

        return DocumentLikenessResult(score=score, edge_density=edge_density, rectangularity=rectangularity)

    @staticmethod
    def _range_score(value: float, low: float, high: float) -> float:
        if low <= value <= high:
            return 1.0
        distance = low - value if value < low else value - high
        return _clamp(1 - distance / 0.7)

    @staticmethod
    def _border_edge_score(edges: Image.Image) -> float:
        width, height = edges.size
        margin_x = max(4, width // 18)
        margin_y = max(4, height // 18)
        bands = [
            edges.crop((0, 0, width, margin_y)),
            edges.crop((0, height - margin_y, width, height)),
            edges.crop((0, 0, margin_x, height)),
            edges.crop((width - margin_x, 0, width, height)),
        ]
        center = edges.crop((margin_x, margin_y, width - margin_x, height - margin_y))
        border_strength = mean(ImageStat.Stat(band).mean[0] for band in bands)
        center_strength = ImageStat.Stat(center).mean[0] or 1
        return _clamp((border_strength / center_strength) / 1.8)


class MrzAnalyzer:
    """MRZ extraction adapter.

    The first pass validates MRZ text if OCR text is provided by a future OCR adapter.
    This keeps ICAO check digit logic local and testable before installing heavy OCR.
    """

    def analyze(self, context: FraudContext, ocr_text: str | None = None) -> OcrResult:
        lines = self._candidate_lines(ocr_text or "")
        selected = self._select_td3_pair(lines)
        if selected is None:
            evidence_score = self._passport_text_evidence_score(ocr_text or "")
            context.checks["passport_text_evidence_score"] = round(evidence_score, 3)
            if evidence_score >= 0.65:
                context.signals.append(_signal("MRZ_NOT_CONFIDENT", "Passport MRZ was not confidently read, but visible passport fields were detected.", "medium", 0.28))
                context.checks["mrz_found"] = False
                context.checks["mrz_soft_fallback"] = True
                return OcrResult(confidence=0.28, mrz_valid=False, mrz_check_digits_valid=False)
            context.signals.append(_signal("MRZ_NOT_READ", "Passport MRZ was not read; upload must contain readable passport evidence.", "high", 0.82))
            context.checks["mrz_found"] = False
            context.checks["mrz_soft_fallback"] = False
            return OcrResult(confidence=0.0, mrz_valid=False, mrz_check_digits_valid=False)

        line1, line2, parsed = selected
        context.checks["mrz_found"] = True
        context.checks["mrz_valid"] = parsed["valid"]
        context.checks["mrz_check_digits_valid"] = parsed["check_digits_valid"]

        if parsed["format_valid"] and not parsed["check_digits_valid"]:
            context.signals.append(_signal("MRZ_CHECK_DIGIT_MISMATCH", "MRZ was read, but one or more check digits did not validate.", "medium", 0.34))
        elif not parsed["format_valid"]:
            context.signals.append(_signal("MRZ_INVALID", "MRZ format is invalid or unreadable.", "medium", 0.42))

        expiry = parsed.get("expiry_date")
        if isinstance(expiry, date):
            if expiry <= date.today():
                context.signals.append(_signal("PASSPORT_EXPIRED", "Passport expiry date is not after today.", "high", 0.95))

        return OcrResult(
            full_name=parsed.get("full_name"),
            passport_number=parsed.get("passport_number"),
            nationality=parsed.get("nationality"),
            date_of_birth=parsed.get("date_of_birth"),
            expiry_date=expiry if isinstance(expiry, date) else None,
            confidence=0.92 if parsed["valid"] else 0.4,
            mrz_text=f"{line1}\n{line2}",
            mrz_valid=parsed["valid"],
            mrz_check_digits_valid=parsed["check_digits_valid"],
            extracted_fields={key: str(value) for key, value in parsed.items() if value is not None},
        )

    @staticmethod
    def _passport_text_evidence_score(text: str) -> float:
        normalized = re.sub(r"[^A-Z0-9< ]", " ", text.upper())
        compact = re.sub(r"\s+", "", normalized)
        score = 0.0
        if "PASSPORT" in normalized or "PDR" in normalized:
            score += 0.18
        if "LAO" in normalized:
            score += 0.16
        if re.search(r"P[A-Z0-9][0-9O]{5,8}", compact):
            score += 0.18
        if re.search(r"[0-3][0-9]\s*(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s*(19|20)[0-9]{2}", normalized):
            score += 0.16
        if re.search(r"(19|20)[0-9]{2}", normalized) and any(month in normalized for month in MONTHS):
            score += 0.08
        latin_name_tokens = re.findall(r"\b[A-Z]{5,}\b", normalized)
        name_like_tokens = [token for token in latin_name_tokens if token not in {"PASSPORT", "NATIONALITY", "AUTHORITY"}]
        if len(name_like_tokens) >= 2:
            score += 0.16
        if "<<" in text or compact.startswith("P") or "POLAO" in compact or "P<LAO" in compact:
            score += 0.08
        return _clamp(score)

    @staticmethod
    def _candidate_lines(text: str) -> list[str]:
        lines = []
        normalized_fragments: list[str] = []
        for line in text.upper().splitlines():
            normalized = re.sub(r"[^A-Z0-9<]", "", line)
            if normalized:
                normalized_fragments.append(normalized)
            normalized = MrzAnalyzer._normalize_ocr_mrz_line(normalized)
            normalized = MrzAnalyzer._recover_short_td3_line(normalized)
            if normalized:
                normalized = normalized[:44].ljust(44, "<")
                if MRZ_ALLOWED.match(normalized):
                    lines.append(normalized)
        for index, fragment in enumerate(normalized_fragments[:-1]):
            stitched = fragment + normalized_fragments[index + 1]
            stitched = MrzAnalyzer._normalize_ocr_mrz_line(stitched)
            stitched = MrzAnalyzer._recover_short_td3_line(stitched)
            if stitched:
                stitched = stitched[:44].ljust(44, "<")
                if MRZ_ALLOWED.match(stitched):
                    lines.append(stitched)
        return lines

    @staticmethod
    def _normalize_ocr_mrz_line(line: str) -> str:
        if not line:
            return line
        chars = list(line)
        if chars[0] == "P" and len(chars) > 1 and chars[1] in {"O", "0"}:
            chars[1] = "<"
        if len(chars) > 5 and chars[0] == "P":
            for index in range(5, len(chars)):
                if chars[index] == "0":
                    chars[index] = "O"
        return "".join(chars)

    @staticmethod
    def _recover_short_td3_line(line: str) -> str | None:
        if not line:
            return None
        if line.startswith("P<") and len(line) >= 20 and "<<" in line:
            return line
        lao_line2 = MrzAnalyzer._recover_lao_line2_from_digit_shift(line)
        if lao_line2:
            return lao_line2
        if len(line) >= 27 and sum(char.isdigit() for char in line) >= 8:
            return line
        # Tesseract often drops the leading "P<L" from Lao passport line 1,
        # turning "P<LAONAME<<GIVEN" into "AONAME<<GIVEN".
        if line.startswith("AO") and len(line) >= 20 and "<<" in line and sum(char.isdigit() for char in line) == 0:
            return f"P<L{line}"
        if line.startswith("LAO") and len(line) >= 20 and "<<" in line and sum(char.isdigit() for char in line) == 0:
            return f"P<{line}"
        return None

    @staticmethod
    def _recover_lao_line2_from_digit_shift(line: str) -> str | None:
        match = re.match(r"^[0-9A-Z]{2}([0-9]{8})(?:00|0O|O0|OO)([0-9]{6})([0-9])([MF<])([0-9]{6})([0-9])", line)
        if match:
            document_candidates = [match.group(1)]
            birth, birth_check, sex, expiry, expiry_check = match.groups()[1:]
        else:
            compressed_match = re.match(r"^([0-9]{9})(?:LA0|LAO|A09)([0-9]{6})([0-9])([A-Z<])([A-Z0-9][0-9]{5})([0-9])", line)
            if not compressed_match:
                return None
            noisy_document = compressed_match.group(1)
            document_candidates = [noisy_document[1:], f"0{noisy_document[2:]}"]
            birth = compressed_match.group(2)
            birth_check = compressed_match.group(3)
            sex = "M" if compressed_match.group(4) not in {"F", "<"} else compressed_match.group(4)
            expiry = compressed_match.group(5).translate(str.maketrans({"S": "3", "B": "8", "O": "0", "I": "1", "L": "1"}))
            expiry_check = compressed_match.group(6)
        if MrzAnalyzer._check_digit(birth) != birth_check:
            return None
        if MrzAnalyzer._check_digit(expiry) != expiry_check:
            return None
        for document_and_check in document_candidates:
            candidate = f"PA{document_and_check}LAO{birth}{birth_check}{sex}{expiry}{expiry_check}"
            if MrzAnalyzer._check_digit(candidate[:9]) != candidate[9]:
                continue
            filler = "<" * 14
            optional_check = "<"
            composite = MrzAnalyzer._check_digit(candidate[:10] + candidate[13:20] + candidate[21:28] + filler + optional_check)
            return f"{candidate}{filler}{optional_check}{composite}"
        return None

    def _select_td3_pair(self, lines: list[str]) -> tuple[str, str, dict[str, Any]] | None:
        best: tuple[float, int, int, str, str, dict[str, Any]] | None = None
        for line1_index, line1 in enumerate(lines):
            if not (line1.startswith("P<") and "<<" in line1):
                continue
            for line2_index, line2 in enumerate(lines):
                if line1_index == line2_index:
                    continue
                parsed = self._parse_td3(line1, line2)
                score = 0.0
                score += 10.0 if parsed["valid"] else 0.0
                score += 4.0 if parsed["format_valid"] else 0.0
                score += 3.0 if parsed["check_digits_valid"] else 0.0
                score += 1.0 if parsed.get("expiry_date") else 0.0
                score += 0.4 if line2_index > line1_index else 0.0
                score += max(0.0, 1.0 - abs((line2_index - line1_index) - 1) * 0.18)
                score += min(len(str(parsed.get("full_name") or "")) / 5.0, 5.0)
                candidate = (score, line1_index, line2_index, line1, line2, parsed)
                if best is None or candidate > best:
                    best = candidate
        if best is None or best[0] <= 0:
            return None
        _, _, _, line1, line2, parsed = best
        return line1, line2, parsed

    def _parse_td3(self, line1: str, line2: str) -> dict[str, Any]:
        if len(line1) != 44 or len(line2) != 44:
            return {"valid": False, "format_valid": False, "check_digits_valid": False}

        line1, line2 = self._normalize_td3_fields(line1, line2)
        document_number = line2[0:9]
        document_check = line2[9]
        birth = line2[13:19]
        birth_check = line2[19]
        expiry = line2[21:27]
        expiry_check = line2[27]
        optional = line2[28:42]
        optional_check = line2[42]
        composite = line2[43]
        format_valid = line1.startswith("P") and document_number.strip("<") != "" and line2[10:13].strip("<") != ""
        document_check_valid = self._check_digit(document_number) == document_check if document_check.isdigit() else False
        birth_check_valid = self._check_digit(birth) == birth_check if birth_check.isdigit() else False
        expiry_check_valid = self._check_digit(expiry) == expiry_check if expiry_check.isdigit() else False
        optional_check_valid = self._check_digit(optional) == optional_check if optional_check.isdigit() else None
        composite_check_valid = (
            self._check_digit(line2[0:10] + line2[13:20] + line2[21:43]) == composite
            if composite.isdigit()
            else None
        )
        primary_checks = [
            document_check_valid,
            birth_check_valid,
            expiry_check_valid,
        ]
        checks = [
            self._check_digit(document_number) == document_check if document_check.isdigit() else False,
            self._check_digit(birth) == birth_check if birth_check.isdigit() else False,
            self._check_digit(expiry) == expiry_check if expiry_check.isdigit() else False,
            optional_check_valid if optional_check_valid is not None else True,
            composite_check_valid if composite_check_valid is not None else True,
        ]
        names = line1[5:44].split("<<", 1)
        surname = self._clean_name_segment(names[0])
        given = self._clean_name_segment(names[1]) if len(names) > 1 else ""
        full_name = " ".join(part for part in [given, surname] if part).strip() or None

        parsed_birth = self._parse_mrz_date(birth, allow_future=False)
        parsed_expiry = self._parse_mrz_date(expiry, allow_future=True)

        primary_check_digits_valid = all(primary_checks)
        check_digits_valid = primary_check_digits_valid and all(checks)
        return {
            "valid": format_valid and primary_check_digits_valid and parsed_expiry is not None,
            "format_valid": format_valid,
            "check_digits_valid": primary_check_digits_valid,
            "all_check_digits_valid": check_digits_valid,
            "document_check_digit_valid": document_check_valid,
            "birth_check_digit_valid": birth_check_valid,
            "expiry_check_digit_valid": expiry_check_valid,
            "optional_check_digit_valid": optional_check_valid,
            "composite_check_digit_valid": composite_check_valid,
            "full_name": full_name,
            "passport_number": document_number.replace("<", ""),
            "nationality": line2[10:13].replace("<", ""),
            "date_of_birth": parsed_birth,
            "expiry_date": parsed_expiry,
            "sex": line2[20],
        }

    @staticmethod
    def _normalize_td3_fields(line1: str, line2: str) -> tuple[str, str]:
        chars = list(line2)
        numeric_positions = set(range(2, 10)) | set(range(13, 20)) | set(range(21, 28)) | {42, 43}
        digit_map = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8"}
        for index in numeric_positions:
            if index < len(chars) and chars[index] in digit_map:
                chars[index] = digit_map[chars[index]]
        return line1, "".join(chars)

    @staticmethod
    def _clean_name_segment(segment: str) -> str:
        # A single "<" separates real name tokens. Runs of two or more "<"
        # start the MRZ filler area; OCR can hallucinate letters inside that
        # filler, so ignore anything after the filler starts.
        meaningful = re.split(r"<{2,}", segment, maxsplit=1)[0]
        tokens = [token for token in meaningful.split("<") if token]
        if len(tokens) > 1 and len(tokens[-1]) == 1:
            tokens = tokens[:-1]
        return " ".join(tokens).strip() or ""

    @staticmethod
    def _check_digit(value: str) -> str:
        total = 0
        for index, char in enumerate(value):
            if char == "<":
                char_value = 0
            elif char.isdigit():
                char_value = int(char)
            elif "A" <= char <= "Z":
                char_value = ord(char) - 55
            else:
                char_value = 0
            total += char_value * MRZ_WEIGHTS[index % 3]
        return str(total % 10)

    @staticmethod
    def _parse_mrz_date(value: str, allow_future: bool) -> date | None:
        if not value.isdigit() or len(value) != 6:
            return None
        year = int(value[:2])
        month = int(value[2:4])
        day = int(value[4:6])
        current_two_digit = date.today().year % 100
        century = 2000 if allow_future or year <= current_two_digit else 1900
        try:
            parsed = date(century + year, month, day)
        except ValueError:
            return None
        if not allow_future and parsed > date.today():
            parsed = date(parsed.year - 100, parsed.month, parsed.day)
        return parsed


class LaoIdCardOcrAnalyzer:
    """Lightweight Lao ID card OCR validator.

    This is intentionally heuristic-first: it supports typed OCR text from tests,
    normal Tesseract output from English labels/digits, and future field-detector
    crops without requiring MRZ.
    """

    KEYWORDS = (
        "LAO",
        "ID",
        "CARD",
        "IDENTITY",
        "NATIONAL",
        "DOB",
        "DATE",
        "BIRTH",
        "EXPIRY",
        "EXPIRE",
        "ISSUE",
        "NAME",
        "SURNAME",
        "GIVEN",
    )

    def analyze(self, context: FraudContext, ocr_text: str | None = None) -> OcrResult:
        text = ocr_text or ""
        raw_text = text
        normalized = self._normalize_text(text)
        context.checks["lao_id_ocr_text_chars"] = len(normalized)

        keyword_hits = sorted({keyword for keyword in self.KEYWORDS if keyword in normalized})
        id_number = self._extract_id_number(normalized)
        dates = self._extract_dates(normalized)
        date_of_birth = self._pick_date(normalized, dates, ("DOB", "BIRTH", "DATE OF BIRTH"))
        expiry_date, expiry_confident = self._pick_lao_id_expiry(normalized, dates)
        full_name = self._extract_name(raw_text, normalized)

        context.checks.update(
            {
                "document_type": "lao_id_card",
                "lao_id_keyword_hits": ",".join(keyword_hits),
                "lao_id_keyword_count": len(keyword_hits),
                "lao_id_number_found": bool(id_number),
                "lao_id_dates_found": len(dates),
                "lao_id_expiry_confident": expiry_confident,
            }
        )

        confidence = 0.15
        confidence += 0.34 if id_number else 0.0
        confidence += min(len(keyword_hits), 5) * 0.07
        confidence += 0.12 if full_name else 0.0
        confidence += 0.1 if date_of_birth else 0.0
        confidence += 0.1 if expiry_date else 0.0
        confidence = _clamp(confidence)

        has_minimum_lao_id_structure = bool(id_number) and len(dates) >= 2
        if len(keyword_hits) < 1 and not has_minimum_lao_id_structure:
            context.signals.append(_signal("LAO_ID_NOT_RECOGNIZED", "Lao ID card text or ID structure was not recognized.", "high", 0.84))
        elif len(keyword_hits) < 2 and not has_minimum_lao_id_structure:
            context.signals.append(_signal("LAO_ID_TEXT_WEAK", "Lao ID card labels were weak or partially unreadable.", "medium", 0.42))
        if not id_number:
            context.signals.append(_signal("LAO_ID_NUMBER_NOT_READ", "Lao ID number was not read from the document.", "high", 0.78))
        if expiry_confident and expiry_date and expiry_date <= date.today():
            context.signals.append(_signal("LAO_ID_EXPIRED", "Lao ID expiry date is not after today.", "high", 0.95))

        return OcrResult(
            document_type="lao_id_card",
            full_name=full_name,
            document_number=id_number,
            id_number=id_number,
            passport_number=None,
            nationality="LAO" if "LAO" in normalized else None,
            date_of_birth=date_of_birth,
            expiry_date=expiry_date,
            confidence=round(confidence, 2),
            mrz_text=None,
            mrz_valid=None,
            mrz_check_digits_valid=None,
            extracted_fields={
                key: value
                for key, value in {
                    "document_number": id_number,
                    "id_number": id_number,
                    "full_name": full_name,
                    "nationality": "LAO" if "LAO" in normalized else None,
                    "date_of_birth": str(date_of_birth) if date_of_birth else None,
                    "expiry_date": str(expiry_date) if expiry_date else None,
                    "keyword_hits": ",".join(keyword_hits),
                }.items()
                if value
            },
        )

    @staticmethod
    def _normalize_text(text: str) -> str:
        upper = text.upper()
        upper = re.sub(r"[^A-Z0-9/\-<:\n .]", " ", upper)
        upper = re.sub(r"[ \t]+", " ", upper)
        return upper

    @staticmethod
    def _extract_id_number(text: str) -> str | None:
        labeled = re.search(r"(?:ID|IDENTITY|NO|NUMBER|CARD)[^\d]{0,12}([0-9][0-9 \-]{5,18}[0-9])", text)
        candidates = []
        if labeled:
            candidates.append(labeled.group(1))
        candidates.extend(re.findall(r"\b[0-9][0-9 \-]{6,18}[0-9]\b", text))
        normalized = [re.sub(r"\D", "", candidate) for candidate in candidates]
        normalized = [candidate for candidate in normalized if 7 <= len(candidate) <= 18]
        if not normalized:
            return None
        return max(normalized, key=len)

    @staticmethod
    def _extract_dates(text: str) -> list[date]:
        text = LaoIdCardOcrAnalyzer._normalize_date_text(text)
        dates: list[date] = []
        for day, month, year in re.findall(r"\b([0-3]?\d)[/\-. ]([01]?\d)[/\-. ]((?:19|20)\d{2})\b", text):
            parsed = LaoIdCardOcrAnalyzer._safe_date(int(year), int(month), int(day))
            if parsed:
                dates.append(parsed)
        for year, month, day in re.findall(r"\b((?:19|20)\d{2})[/\-. ]([01]?\d)[/\-. ]([0-3]?\d)\b", text):
            parsed = LaoIdCardOcrAnalyzer._safe_date(int(year), int(month), int(day))
            if parsed:
                dates.append(parsed)
        for day, month_name, year in re.findall(r"\b([0-3]?\d)\s+([A-Z]{3})\s+((?:19|20)\d{2})\b", text):
            month = MONTHS.get(month_name)
            if month:
                parsed = LaoIdCardOcrAnalyzer._safe_date(int(year), month, int(day))
                if parsed:
                    dates.append(parsed)
        unique = []
        for parsed in dates:
            if parsed not in unique:
                unique.append(parsed)
        return unique

    @staticmethod
    def _pick_date(text: str, dates: list[date], labels: tuple[str, ...]) -> date | None:
        labeled = LaoIdCardOcrAnalyzer._pick_labeled_date(text, labels)
        if labeled:
            return labeled
        if not dates:
            return None
        past_dates = [item for item in dates if item < date.today()]
        return min(past_dates) if past_dates else None

    @staticmethod
    def _pick_labeled_date(text: str, labels: tuple[str, ...]) -> date | None:
        text = LaoIdCardOcrAnalyzer._normalize_date_text(text)
        for label in labels:
            match = re.search(label + r".{0,30}?((?:[0-3]?\d[/\-. ][01]?\d[/\-. ](?:19|20)\d{2})|(?:(?:19|20)\d{2}[/\-. ][01]?\d[/\-. ][0-3]?\d)|(?:[0-3]?\d\s+[A-Z]{3}\s+(?:19|20)\d{2}))", text)
            if match:
                parsed_dates = LaoIdCardOcrAnalyzer._extract_dates(match.group(1))
                if parsed_dates:
                    return parsed_dates[0]
        return None

    @staticmethod
    def _pick_lao_id_expiry(text: str, dates: list[date]) -> tuple[date | None, bool]:
        labeled = LaoIdCardOcrAnalyzer._pick_labeled_date(text, ("EXPIRY", "EXPIRE", "VALID UNTIL", "VALID TO"))
        if labeled:
            return labeled, True
        future_dates = [item for item in dates if item > date.today()]
        if future_dates:
            return max(future_dates), True
        # Lao ID captures often contain birth and issue dates even when the
        # expiry label/date OCR is weak. Do not mark the document expired by
        # treating the issue date as expiry.
        return None, False

    @staticmethod
    def _normalize_date_text(text: str) -> str:
        text = re.sub(r"\s*([/\-.])\s*", r"\1", text)
        digitish_map = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "B": "8", "S": "5"})

        def clean_token(match: re.Match[str]) -> str:
            return match.group(0).translate(digitish_map)

        return re.sub(r"\b[0-9OQDILBS][0-9OQDILBS/\-.]{3,12}[0-9OQDILBS]\b", clean_token, text)

    @staticmethod
    def _safe_date(year: int, month: int, day: int) -> date | None:
        try:
            return date(year, month, day)
        except ValueError:
            return None

    @staticmethod
    def _extract_name(raw_text: str, normalized_text: str | None = None) -> str | None:
        normalized = normalized_text or LaoIdCardOcrAnalyzer._normalize_text(raw_text)
        line_name = LaoIdCardOcrAnalyzer._extract_name_from_lines(raw_text)
        if line_name:
            return line_name
        name_patterns = [
            r"(?:FULL\s+NAME|NAME)[ :]+([A-Z][A-Z ]{2,60})",
            r"(?:SURNAME|FAMILY\s+NAME)[ :]+([A-Z][A-Z ]{2,35}).{0,20}(?:GIVEN\s+NAME|GIVEN|FIRST\s+NAME)[ :]+([A-Z][A-Z ]{2,35})",
        ]
        for pattern in name_patterns:
            match = re.search(pattern, normalized, re.DOTALL)
            if not match:
                continue
            parts = [" ".join(group.split()) for group in match.groups() if group]
            cleaned = " ".join(parts)
            cleaned = re.sub(r"\b(?:LAO|ID|CARD|DOB|DATE|BIRTH|EXPIRY|ISSUE|NATIONALITY)\b.*", "", cleaned).strip()
            if 3 <= len(cleaned) <= 80:
                return cleaned
        return None

    @staticmethod
    def _extract_name_from_lines(text: str) -> str | None:
        lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
        lines = [line for line in lines if line]

        surname = LaoIdCardOcrAnalyzer._line_after_label(lines, ("SURNAME", "FAMILY NAME", "NOM"))
        given = LaoIdCardOcrAnalyzer._line_after_label(lines, ("GIVEN", "FIRST NAME", "PRENOMS", "PR NOMS"))
        if surname or given:
            combined = " ".join(part for part in [surname, given] if part)
            cleaned = LaoIdCardOcrAnalyzer._clean_name_candidate(combined)
            if cleaned:
                return cleaned

        lao_label_name = LaoIdCardOcrAnalyzer._extract_lao_label_name(lines)
        if lao_label_name:
            return lao_label_name

        candidates = [LaoIdCardOcrAnalyzer._clean_name_candidate(line) for line in lines]
        candidates = [candidate for candidate in candidates if candidate]
        if len(candidates) >= 2 and all(LaoIdCardOcrAnalyzer._is_single_latin_name(candidate) for candidate in candidates[:2]):
            return " ".join(candidates[:2])
        return candidates[0] if candidates else None

    @staticmethod
    def _line_after_label(lines: list[str], labels: tuple[str, ...]) -> str | None:
        for index, line in enumerate(lines):
            upper = line.upper()
            if not any(label in upper for label in labels):
                continue
            same_line = re.split("|".join(re.escape(label) for label in labels), upper, maxsplit=1)
            if len(same_line) > 1:
                cleaned = LaoIdCardOcrAnalyzer._clean_name_candidate(same_line[1])
                if cleaned:
                    return cleaned
            for candidate in lines[index + 1 : index + 3]:
                cleaned = LaoIdCardOcrAnalyzer._clean_name_candidate(candidate)
                if cleaned:
                    return cleaned
        return None

    @staticmethod
    def _extract_lao_label_name(lines: list[str]) -> str | None:
        label_pattern = re.compile(r"(?:ຊື່|ສະກຸນ|ນາມສະກຸນ)")
        lao_text_pattern = re.compile(r"[\u0E80-\u0EFF]{2,}(?:\s+[\u0E80-\u0EFF]{2,})*")
        for index, line in enumerate(lines):
            if not label_pattern.search(line):
                continue
            after_label = label_pattern.sub(" ", line)
            after_label = re.sub(r"^\s*(?:ແລະ|ກັບ)\s+", "", after_label)
            match = lao_text_pattern.search(after_label)
            if match:
                return re.sub(r"\s+", " ", match.group(0)).strip()
            for candidate in lines[index + 1 : index + 3]:
                match = lao_text_pattern.search(candidate)
                if match:
                    return re.sub(r"\s+", " ", match.group(0)).strip()
        return None

    @staticmethod
    def _clean_name_candidate(value: str) -> str | None:
        value = re.sub(r"[^A-Za-z\u0E80-\u0EFF' -]", " ", value)
        value = re.sub(r"\s+", " ", value).strip(" -'")
        if not value:
            return None
        upper = value.upper()
        stop_words = {
            "LAO",
            "LAO PDR",
            "RDP LAO",
            "ID",
            "CARD",
            "NAME",
            "NAMES",
            "GIVEN",
            "SURNAME",
            "FAMILY",
            "PRENOMS",
            "NOM",
            "NATIONAL",
            "NATIONALITY",
            "DATE",
            "BIRTH",
            "EXPIRY",
            "EXPIRE",
            "ISSUE",
            "SEX",
            "MALE",
            "FEMALE",
            "AUTHORITY",
            "MOFA",
            "PDR",
        }
        words = upper.split()
        if upper in stop_words or any(word in stop_words for word in words):
            return None
        if re.search(r"\b(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\b", upper):
            return None
        if not re.search(r"[A-Za-z\u0E80-\u0EFF]", value):
            return None
        if len(value) < 3 or len(value) > 80:
            return None
        return upper if re.search(r"[A-Za-z]", value) else value

    @staticmethod
    def _is_single_latin_name(value: str) -> bool:
        return bool(re.fullmatch(r"[A-Z' -]{2,35}", value)) and len(value.split()) == 1


class ForensicAnalyzer:
    def analyze(self, context: FraudContext) -> ForensicResult:
        ela_score = self._ela_score(context.image)
        blockiness = self._jpeg_blockiness(context.image)
        saturation_extreme_ratio = self._saturation_extremes(context.image)
        glare_risk = max(float(context.checks.get("glare_ratio", 0) or 0) - 0.1, 0)
        recapture_risk = _clamp((blockiness * 0.52) + (saturation_extreme_ratio * 0.24) + (glare_risk * 0.9))
        tamper_risk = _clamp((ela_score * 0.68) + (blockiness * 0.24) + (saturation_extreme_ratio * 0.08))

        context.checks.update(
            {
                "ela_score": round(ela_score, 3),
                "jpeg_blockiness": round(blockiness, 3),
                "saturation_extreme_ratio": round(saturation_extreme_ratio, 4),
            }
        )

        if recapture_risk >= 0.62:
            context.signals.append(_signal("RECAPTURE_RISK_HIGH", "Screen, print, or photocopy recapture artifacts are elevated.", "high", recapture_risk))
        elif recapture_risk >= 0.44:
            context.signals.append(_signal("RECAPTURE_RISK_MEDIUM", "Possible screen or print recapture artifacts were detected.", "medium", recapture_risk))

        if tamper_risk >= 0.64:
            context.signals.append(_signal("TAMPER_RISK_HIGH", "Image forensics indicate possible edited or pasted document regions.", "high", tamper_risk))
        elif tamper_risk >= 0.46:
            context.signals.append(_signal("TAMPER_RISK_MEDIUM", "Image forensics show inconsistent compression or editing artifacts.", "medium", tamper_risk))

        return ForensicResult(
            recapture_risk=recapture_risk,
            tamper_risk=tamper_risk,
            ela_score=ela_score,
            blockiness=blockiness,
            saturation_extreme_ratio=saturation_extreme_ratio,
        )

    @staticmethod
    def _ela_score(image: Image.Image) -> float:
        resized = image.copy()
        buffer = BytesIO()
        resized.save(buffer, "JPEG", quality=88)
        buffer.seek(0)
        recompressed = Image.open(buffer).convert("RGB")
        diff = ImageChops.difference(resized, recompressed)
        stat = ImageStat.Stat(diff)
        channel_mean = sum(stat.mean) / 3
        channel_std = sum(stat.stddev) / 3
        return _clamp(((channel_mean / 18) * 0.55) + ((channel_std / 24) * 0.45))

    @staticmethod
    def _jpeg_blockiness(image: Image.Image) -> float:
        gray = ImageOps.grayscale(image.resize((512, max(1, round(512 / (image.width / max(image.height, 1)))))))
        width, height = gray.size
        data = list(gray.getdata())

        def px(x: int, y: int) -> int:
            return data[y * width + x]

        boundary_diffs: list[int] = []
        inner_diffs: list[int] = []
        for y in range(height):
            for x in range(1, width):
                diff = abs(px(x, y) - px(x - 1, y))
                if x % 8 == 0:
                    boundary_diffs.append(diff)
                elif x % 8 == 4:
                    inner_diffs.append(diff)
        if not boundary_diffs or not inner_diffs:
            return 0.0
        ratio = (mean(boundary_diffs) + 1) / (mean(inner_diffs) + 1)
        return _clamp((ratio - 1.05) / 1.45)

    @staticmethod
    def _saturation_extremes(image: Image.Image) -> float:
        hsv = image.convert("HSV").resize((320, max(1, round(320 / (image.width / max(image.height, 1))))))
        pixels = hsv.getdata()
        total = hsv.width * hsv.height
        extreme = 0
        for _, sat, val in pixels:
            if sat > 235 or val < 8:
                extreme += 1
        return extreme / max(total, 1)


class RiskScorer:
    def score(
        self,
        context: FraudContext,
        quality: QualityResult,
        document: DocumentLikenessResult,
        forensic: ForensicResult,
        model_ensemble: DocumentModelEnsembleResult,
        ocr: OcrResult,
    ) -> DocumentAnalysis:
        hard_fail_codes = {
            "NON_IMAGE_UPLOAD",
            "UNSUPPORTED_FILE_TYPE",
            "LOW_RESOLUTION",
            "BLUR_DETECTED",
            "NON_DOCUMENT_UPLOAD",
            "MRZ_NOT_READ",
            "MRZ_INVALID",
            "MRZ_CHECK_DIGIT_MISMATCH",
            "PASSPORT_EXPIRED",
            "LAO_ID_NOT_RECOGNIZED",
            "LAO_ID_NUMBER_NOT_READ",
            "LAO_ID_EXPIRED",
            "TAMPER_RISK_HIGH",
            "RECAPTURE_RISK_HIGH",
            "DOCUMENT_TAMPER_MODEL_RISK_HIGH",
            "DOCUMENT_RECAPTURE_MODEL_RISK_HIGH",
            "DOCUMENT_PRINT_COPY_RISK_HIGH",
            "DOCUMENT_FRAUD_MODEL_RISK_HIGH",
            "DOCUMENT_FACE_SUBSTITUTION_RISK_HIGH",
        }

        severity_weight = {"low": 0.16, "medium": 0.34, "high": 0.62}
        signal_pressure = sum(severity_weight[signal.severity] * signal.score for signal in context.signals)
        quality_pressure = (1 - quality.score) * 0.34
        document_pressure = (1 - document.score) * 0.3
        model_pressure = (
            model_ensemble.document_fraud_risk * 0.34
            + model_ensemble.recapture_risk * 0.12
            + model_ensemble.tamper_risk * 0.16
        ) * max(model_ensemble.confidence, 0.35)
        risk = _clamp(
            signal_pressure
            + quality_pressure
            + document_pressure
            + forensic.recapture_risk * 0.22
            + forensic.tamper_risk * 0.28
            + model_pressure
        )

        has_hard_fail = any(signal.code in hard_fail_codes for signal in context.signals)
        status = "rejected" if has_hard_fail or risk > 0.72 or quality.score < 0.34 or document.score < 0.34 else "passed"

        return DocumentAnalysis(
            status=status,
            image_quality_score=round(quality.score, 2),
            fraud_risk_score=round(risk, 2),
            document_likeness_score=round(document.score, 2),
            recapture_risk_score=round(forensic.recapture_risk, 2),
            tamper_risk_score=round(forensic.tamper_risk, 2),
            ocr=ocr,
            signals=context.signals,
            checks=context.checks,
        )


class PassportFraudAnalyzer:
    """Passport fraud detection pipeline with local heuristics and model-ready adapters."""

    def __init__(self, model_ensemble: DocumentFraudModelEnsemble | None = None) -> None:
        self.loader = ImageLoader()
        self.quality = QualityAnalyzer()
        self.document = DocumentLikenessAnalyzer()
        self.ocr = OcrTextExtractor()
        self.mrz = MrzAnalyzer()
        self.forensics = ForensicAnalyzer()
        self.models = model_ensemble or DocumentFraudModelEnsemble()
        self.scorer = RiskScorer()

    def analyze(self, content: bytes, filename: str, ocr_text: str | None = None) -> DocumentAnalysis:
        loaded = self.loader.load(content, filename)
        if isinstance(loaded, DocumentAnalysis):
            return loaded

        context = loaded
        context.checks["document_type"] = "passport"
        quality = self.quality.analyze(context)
        document = self.document.analyze(context)
        extracted_text = ocr_text if ocr_text is not None else self.ocr.extract(context, document_type="passport")
        ocr = self.mrz.analyze(context, ocr_text=extracted_text)
        forensic = self.forensics.analyze(context)
        context.checks.update(
            {
                "quality_score": round(quality.score, 3),
                "forensic_recapture_risk": round(forensic.recapture_risk, 3),
                "forensic_tamper_risk": round(forensic.tamper_risk, 3),
            }
        )
        model_result = self.models.analyze(DocumentModelInput(image=context.image, checks=context.checks))
        context.checks.update(model_result.checks)
        context.signals.extend(model_result.signals)
        return self.scorer.score(context, quality, document, forensic, model_result, ocr)


class LaoIdCardFraudAnalyzer:
    """Lao government ID card verification with local heuristics and OCR."""

    def __init__(self, model_ensemble: DocumentFraudModelEnsemble | None = None) -> None:
        self.loader = ImageLoader()
        self.quality = QualityAnalyzer()
        self.document = DocumentLikenessAnalyzer()
        self.ocr = OcrTextExtractor()
        self.id_ocr = LaoIdCardOcrAnalyzer()
        self.forensics = ForensicAnalyzer()
        self.models = model_ensemble or DocumentFraudModelEnsemble()
        self.scorer = RiskScorer()

    def analyze(self, content: bytes, filename: str, ocr_text: str | None = None) -> DocumentAnalysis:
        loaded = self.loader.load(content, filename)
        if isinstance(loaded, DocumentAnalysis):
            loaded.ocr.document_type = "lao_id_card"
            return loaded

        context = loaded
        context.checks["document_type"] = "lao_id_card"
        quality = self.quality.analyze(context)
        document = self.document.analyze(context)
        extracted_text = ocr_text if ocr_text is not None else self.ocr.extract(context, document_type="lao_id_card")
        ocr = self.id_ocr.analyze(context, ocr_text=extracted_text)
        forensic = self.forensics.analyze(context)
        context.checks.update(
            {
                "quality_score": round(quality.score, 3),
                "forensic_recapture_risk": round(forensic.recapture_risk, 3),
                "forensic_tamper_risk": round(forensic.tamper_risk, 3),
            }
        )
        model_result = self.models.analyze(DocumentModelInput(image=context.image, checks=context.checks))
        context.checks.update(model_result.checks)
        context.signals.extend(model_result.signals)
        return self.scorer.score(context, quality, document, forensic, model_result, ocr)
