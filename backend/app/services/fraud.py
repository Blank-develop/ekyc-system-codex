from __future__ import annotations

import math
import re
import shutil
from dataclasses import dataclass, field
from datetime import date
from io import BytesIO
from statistics import mean
from typing import Any

from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError

from app.models.schemas import DocumentAnalysis, FraudSignal, OcrResult
from app.services.document_models import DocumentFraudModelEnsemble, DocumentModelEnsembleResult, DocumentModelInput


SUPPORTED_IMAGE_TYPES = (".jpg", ".jpeg", ".png", ".webp")
MRZ_ALLOWED = re.compile(r"^[A-Z0-9<]{44}$")
MRZ_WEIGHTS = (7, 3, 1)


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
        self.tesseract_path = shutil.which("tesseract")

    def extract(self, context: FraudContext) -> str | None:
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
        for name, image in self._ocr_regions(context.image):
            prepared = self._prepare_for_ocr(image)
            config = "--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
            try:
                text = pytesseract.image_to_string(prepared, config=config)
            except pytesseract.TesseractError as exc:
                context.checks["ocr_error"] = str(exc)
                continue
            if text.strip():
                context.checks[f"ocr_{name}_chars"] = len(text)
                text_blocks.append(text)

        merged = "\n".join(text_blocks).strip()
        context.checks["ocr_text_chars"] = len(merged)
        if not merged:
            context.signals.append(_signal("OCR_TEXT_NOT_FOUND", "OCR did not extract readable passport text.", "medium", 0.32))
            return None
        return merged

    @staticmethod
    def _ocr_regions(image: Image.Image) -> list[tuple[str, Image.Image]]:
        width, height = image.size
        return [
            ("full", image),
            ("bottom_45", image.crop((0, int(height * 0.55), width, height))),
            ("bottom_32", image.crop((0, int(height * 0.68), width, height))),
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
            context.signals.append(_signal("MRZ_NOT_READ", "Passport MRZ was not read; upload must contain readable passport evidence.", "high", 0.82))
            context.checks["mrz_found"] = False
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
    def _candidate_lines(text: str) -> list[str]:
        lines = []
        for line in text.upper().splitlines():
            normalized = re.sub(r"[^A-Z0-9<]", "", line)
            normalized = MrzAnalyzer._normalize_ocr_mrz_line(normalized)
            normalized = MrzAnalyzer._recover_short_td3_line(normalized)
            if normalized:
                normalized = normalized[:44].ljust(44, "<")
                if MRZ_ALLOWED.match(normalized):
                    lines.append(normalized)
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
        if len(line) >= 27 and sum(char.isdigit() for char in line) >= 8:
            return line
        # Tesseract often drops the leading "P<L" from Lao passport line 1,
        # turning "P<LAONAME<<GIVEN" into "AONAME<<GIVEN".
        if line.startswith("AO") and len(line) >= 20 and "<<" in line and sum(char.isdigit() for char in line) == 0:
            return f"P<L{line}"
        if line.startswith("LAO") and len(line) >= 20 and "<<" in line and sum(char.isdigit() for char in line) == 0:
            return f"P<{line}"
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
            "TAMPER_RISK_HIGH",
            "RECAPTURE_RISK_HIGH",
            "DOCUMENT_TAMPER_MODEL_RISK_HIGH",
            "DOCUMENT_RECAPTURE_MODEL_RISK_HIGH",
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
        quality = self.quality.analyze(context)
        document = self.document.analyze(context)
        extracted_text = ocr_text if ocr_text is not None else self.ocr.extract(context)
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
