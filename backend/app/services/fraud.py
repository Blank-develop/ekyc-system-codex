from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher
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

        # Fast path for an open passport photographed vertically from farther
        # away. Its identity page usually occupies the middle of the frame, so
        # a small targeted MRZ pass can validate the document before the much
        # slower full-page/orientation fallback OCR runs.
        if document_type == "passport" and context.height > context.width * 1.08:
            width, height = context.image.size
            mid_page = context.image.crop(
                (
                    int(width * 0.08),
                    int(height * 0.50),
                    int(width * 0.92),
                    int(height * 0.66),
                )
            )
            prepared = self._prepare_for_mrz_ocr_soft(mid_page, target=1400)
            mrz_config = "--oem 3 --psm 11 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
            try:
                mid_page_text = pytesseract.image_to_string(prepared, lang="eng", config=mrz_config)
            except pytesseract.TesseractError as exc:
                context.checks["ocr_mrz_error"] = str(exc)
            else:
                if mid_page_text.strip():
                    context.checks["ocr_mrz_mid_page_fast_chars"] = len(mid_page_text)
                    candidate_lines = MrzAnalyzer._candidate_lines(mid_page_text)
                    selected = MrzAnalyzer()._select_td3_pair(candidate_lines)
                    if selected is not None and selected[2].get("valid"):
                        merged = mid_page_text.strip()
                        context.checks["ocr_fast_mid_page"] = True
                        context.checks["ocr_text_chars"] = len(merged)
                        return merged

        for name, image in self._ocr_regions(
            context.image,
            include_passport_rotations=document_type == "passport",
        ):
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
            # Lao passport numbers are printed in the upper-right of the
            # identity page, well above the MRZ. On portrait open-book photos,
            # full-page OCR often inserts spaces between ``PA`` and the seven
            # digits while the MRZ pass loses the same prefix. Preserve one
            # tight visual-field read as independent evidence for the
            # checksum-gated MRZ consensus below.
            merged_visual_text = "\n".join(text_blocks).upper()
            if context.height > context.width * 1.08 and "LAO" in merged_visual_text:
                width, height = context.image.size
                number_zone = context.image.crop(
                    (
                        int(width * 0.68),
                        int(height * 0.54),
                        int(width * 0.98),
                        int(height * 0.64),
                    )
                ).convert("L")
                number_zone = number_zone.resize(
                    (number_zone.width * 3, number_zone.height * 3),
                    Image.Resampling.LANCZOS,
                )
                try:
                    number_text = pytesseract.image_to_string(
                        number_zone,
                        lang="eng",
                        config="--oem 3 --psm 6",
                    )
                except pytesseract.TesseractError as exc:
                    context.checks["ocr_visual_document_number_error"] = str(exc)
                else:
                    if number_text.strip():
                        context.checks["ocr_visual_document_number_chars"] = len(number_text)
                        text_blocks.append(number_text)

            mrz_config = "--oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
            for name, image, psm in self._passport_mrz_regions(context.image):
                # The tight low-resolution crop is intentionally grayscale:
                # adaptive thresholding turns soft Australian MRZ chevrons into
                # K/C/R glyphs and destroys otherwise useful character reads.
                if "_rotated_framed" in name:
                    variants = [(name, self._prepare_for_rotated_mrz_ocr(image))]
                elif "_tight_soft" in name:
                    if name.startswith("mrz_mid_page_"):
                        soft_target = 1400
                    elif "_bottom_safe_" in name:
                        soft_target = 3400
                    else:
                        soft_target = 3200 if name == "mrz_bottom_28_tight_soft" else 2600
                    variants = [(name, self._prepare_for_mrz_ocr_soft(image, target=soft_target))]
                else:
                    variants = [(name, self._prepare_for_mrz_ocr(image))]
                # Textured passport backgrounds can be damaged by adaptive
                # thresholding. Keep a softer grayscale pass for the two full
                # orientation candidates; this recovers sideways MRZ bands
                # without doubling every OCR crop in the normal path.
                if name in {"mrz_rot270_bottom_30", "mrz_rot90_bottom_30"}:
                    variants.append((f"{name}_soft", self._prepare_for_mrz_ocr_soft(image)))
                # Glare bands across the laminate (typical of hand-held US
                # passport photos) survive divide-by-background normalization
                # but are destroyed by adaptive thresholding. One extra pass on
                # the two upright bottom-band crops only.
                if name in {"mrz_bottom_22", "mrz_bottom_30"}:
                    variants.append((f"{name}_glare", self._prepare_for_mrz_ocr_glare(image)))
                if name == "mrz_bottom_22":
                    variants.append((f"{name}_glare_binary", self._prepare_for_mrz_ocr_glare(image, binarize=True)))
                if "_bottom_safe_" in name:
                    variants.append((f"{name}_glare", self._prepare_for_mrz_ocr_glare(image)))
                for variant_name, prepared in variants:
                    try:
                        text = pytesseract.image_to_string(prepared, lang="eng", config=f"{mrz_config} --psm {psm}")
                    except pytesseract.TesseractError as exc:
                        context.checks["ocr_mrz_error"] = str(exc)
                        continue
                    if text.strip():
                        context.checks[f"ocr_{variant_name}_chars"] = len(text)
                        text_blocks.append(text)
                        selected = MrzAnalyzer()._select_td3_pair(
                            MrzAnalyzer._candidate_lines("\n".join(text_blocks))
                        )
                        if selected is not None and selected[2].get("valid"):
                            # The bottom-safe pass deliberately has two
                            # complementary variants: soft grayscale preserves
                            # the number/date line, while glare normalization
                            # usually preserves the country/name line. Do not
                            # finalize from the first half alone; its damaged
                            # nationality is not check-digit protected and can
                            # otherwise pair with an older noisy name line.
                            if "_bottom_safe_" in variant_name and not variant_name.endswith("_glare"):
                                continue
                            context.checks["ocr_fast_mrz_region"] = variant_name
                            if "_rotated_framed" in variant_name:
                                degrees_match = re.search(r"rot(90|270)", variant_name)
                                if degrees_match:
                                    rotated = context.image.rotate(int(degrees_match.group(1)), expand=True)
                                    visual_zone = rotated.crop(
                                        (
                                            int(rotated.width * 0.15),
                                            int(rotated.height * 0.08),
                                            int(rotated.width * 0.90),
                                            int(rotated.height * 0.68),
                                        )
                                    )
                                    try:
                                        visual_text = pytesseract.image_to_string(
                                            self._prepare_for_ocr(visual_zone),
                                            lang="eng",
                                            config="--oem 3 --psm 6",
                                        )
                                    except pytesseract.TesseractError as exc:
                                        context.checks["ocr_rotated_visual_error"] = str(exc)
                                    else:
                                        if visual_text.strip():
                                            context.checks["ocr_rotated_visual_chars"] = len(visual_text)
                                            text_blocks.append(visual_text)
                            merged = "\n".join(text_blocks).strip()
                            context.checks["ocr_text_chars"] = len(merged)
                            return merged

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
    def _ocr_regions(
        image: Image.Image,
        include_passport_rotations: bool = False,
    ) -> list[tuple[str, Image.Image]]:
        width, height = image.size
        regions = [
            ("full", image),
            ("bottom_45", image.crop((0, int(height * 0.55), width, height))),
            ("bottom_32", image.crop((0, int(height * 0.68), width, height))),
        ]
        # A landscape passport photographed sideways is commonly stored in a
        # portrait pixel canvas without EXIF orientation. The thresholded MRZ
        # crops below can lose characters on display/moire captures, while the
        # normal full-page pass remains readable after rotation. Run both
        # directions only for portrait-shaped passport uploads, limiting the
        # additional OCR cost to images that plausibly need orientation repair.
        if include_passport_rotations and height > width * 1.08:
            regions.extend(
                [
                    ("full_rot90", image.rotate(90, expand=True)),
                    ("full_rot270", image.rotate(270, expand=True)),
                ]
            )
        return regions

    @staticmethod
    def _passport_mrz_regions(image: Image.Image) -> list[tuple[str, Image.Image, int]]:
        width, height = image.size
        rotated_90 = image.rotate(90, expand=True)
        rotated_270 = image.rotate(270, expand=True)
        regions = [
            # Upright passports: the MRZ is the bottom band. These were missing,
            # so upright captures previously only reached the milder general OCR.
            ("mrz_bottom_22", image.crop((0, int(height * 0.78), width, height)), 6),
            ("mrz_bottom_22_sparse", image.crop((0, int(height * 0.78), width, height)), 11),
            ("mrz_bottom_30", image.crop((0, int(height * 0.70), width, height)), 6),
            ("mrz_bottom_30_sparse", image.crop((0, int(height * 0.70), width, height)), 11),
            # Soft, full-width band for small open-book captures. Keeping the
            # page edge is useful when the two MRZ baselines sit very close to
            # the bottom of the photo; hard thresholding commonly changes the
            # protected AUS date digits on this layout.
            ("mrz_bottom_28_tight_soft", image.crop((0, int(height * 0.72), width, height)), 6),
            # Exclude the page edge/background below the document. On small,
            # soft captures this gives Tesseract enough vertical context for
            # both TD3 lines without letting the fabric/table edge join them.
            ("mrz_bottom_25_tight_soft", image.crop((0, int(height * 0.75), width, int(height * 0.98))), 6),
            ("mrz_bottom_25_tight_soft_sparse", image.crop((0, int(height * 0.75), width, int(height * 0.98))), 11),
        ]
        if height > width * 1.08:
            # Sideways open-book photos often include background beneath the
            # passport. After rotation, crop to the physical page instead of
            # the bottom of the whole camera frame; otherwise the MRZ's second
            # line is diluted by bedding/table pixels and thresholding erases
            # it. Keep a small horizontal inset to remove fingers/page edges.
            for degrees, rotated in ((90, rotated_90), (270, rotated_270)):
                regions.append(
                    (
                        f"mrz_rot{degrees}_rotated_framed",
                        rotated.crop(
                            (
                                int(rotated.width * 0.05),
                                int(rotated.height * 0.66),
                                int(rotated.width * 0.98),
                                int(rotated.height * 0.94),
                            )
                        ),
                        6,
                    )
                )
                # When the passport fills the camera frame, the second TD3
                # line can sit below the framed crop's old 94% boundary. Keep
                # an almost edge-to-edge, softly processed band as a separate
                # sparse-text pass. This is especially important for sideways
                # captures where the page edge, not the camera-frame edge,
                # defines the MRZ baseline.
                regions.append(
                    (
                        f"mrz_rot{degrees}_bottom_safe_tight_soft",
                        rotated.crop(
                            (
                                int(rotated.width * 0.01),
                                int(rotated.height * 0.78),
                                int(rotated.width * 0.995),
                                int(rotated.height * 0.995),
                            )
                        ),
                        11,
                    )
                )
        regions.extend(
            [
            # Generic rotated captures (MRZ along a vertical edge).
            ("mrz_right_65_rot270", image.crop((int(width * 0.65), 0, width, height)).rotate(270, expand=True), 6),
            ("mrz_right_65_rot270_sparse", image.crop((int(width * 0.65), 0, width, height)).rotate(270, expand=True), 11),
            ("mrz_rot270_bottom_30", rotated_270.crop((0, int(rotated_270.height * 0.70), rotated_270.width, rotated_270.height)), 6),
            ("mrz_rot270_bottom_30_sparse", rotated_270.crop((0, int(rotated_270.height * 0.70), rotated_270.width, rotated_270.height)), 11),
            ("mrz_rot90_bottom_30", rotated_90.crop((0, int(rotated_90.height * 0.70), rotated_90.width, rotated_90.height)), 6),
            ]
        )
        return regions

    @staticmethod
    def _normalize_ocr_gray(gray: Image.Image) -> Image.Image:
        """Illumination normalization for OCR: CLAHE evens out shadows/uneven
        lighting across a document photo, and a gamma pull toward mid-tone
        rescues dark or washed-out captures. Falls back to global autocontrast
        when OpenCV is unavailable. Near-identity for an evenly-lit scan."""
        try:
            import cv2
            import numpy as np
        except ImportError:
            return ImageOps.autocontrast(gray)
        source = np.asarray(gray)
        mean = float(source.mean()) / 255.0
        # Only rescue genuinely dark or washed-out captures. A well-exposed
        # document stays on the original autocontrast path -- CLAHE can otherwise
        # alter already-crisp MRZ glyphs (e.g. read "P" as "M") and break a check
        # digit, so we must not touch images that don't need help.
        if 0.20 <= mean <= 0.80:
            return ImageOps.autocontrast(gray)
        array = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(source)
        if 0.02 < mean < 0.98:
            exponent = float(np.clip(np.log(0.5) / np.log(mean), 0.5, 2.0))
            lut = (np.clip((np.arange(256) / 255.0) ** exponent, 0, 1) * 255).astype(np.uint8)
            array = lut[array]
        return Image.fromarray(array)

    @staticmethod
    def _prepare_for_ocr(image: Image.Image) -> Image.Image:
        gray = ImageOps.grayscale(image)
        longest_side = max(gray.size)
        if longest_side < 1800:
            scale = math.ceil(1800 / longest_side)
            gray = gray.resize((gray.width * scale, gray.height * scale), Image.Resampling.LANCZOS)
        gray = OcrTextExtractor._normalize_ocr_gray(gray)
        gray = gray.filter(ImageFilter.SHARPEN)
        return gray

    @staticmethod
    def _prepare_for_mrz_ocr(image: Image.Image) -> Image.Image:
        gray = ImageOps.grayscale(image)
        # MRZ glyphs in these captures are tiny (median image ~726px wide, so a
        # TD3 character is only ~6-10px tall -- near Tesseract's readability
        # floor). Upscale the crop aggressively with a smooth fractional LANCZOS
        # resize (vs the general OCR path's coarse integer scale to 1800px) so
        # character strokes are large enough to recognise.
        longest = max(gray.size)
        target = 2600
        if 0 < longest < target:
            scale = min(target / longest, 4.0)
            gray = gray.resize(
                (max(1, round(gray.width * scale)), max(1, round(gray.height * scale))),
                Image.Resampling.LANCZOS,
            )
        gray = OcrTextExtractor._normalize_ocr_gray(gray)
        gray = gray.filter(ImageFilter.SHARPEN)
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

    @staticmethod
    def _prepare_for_mrz_ocr_soft(image: Image.Image, target: int = 2600) -> Image.Image:
        """Preserve fine MRZ strokes when thresholding erases textured text."""
        gray = ImageOps.autocontrast(ImageOps.grayscale(image))
        longest = max(gray.size)
        if 0 < longest < target:
            scale = min(target / longest, 5.0 if target > 2600 else 4.0)
            gray = gray.resize(
                (max(1, round(gray.width * scale)), max(1, round(gray.height * scale))),
                Image.Resampling.LANCZOS,
            )
        return gray.filter(ImageFilter.SHARPEN)

    @staticmethod
    def _prepare_for_rotated_mrz_ocr(image: Image.Image) -> Image.Image:
        """Prepare a framed sideways MRZ without amplifying page texture."""
        gray = ImageOps.grayscale(image)
        if gray.width and gray.width < 3000:
            scale = min(3000 / gray.width, 4.0)
            gray = gray.resize(
                (max(1, round(gray.width * scale)), max(1, round(gray.height * scale))),
                Image.Resampling.LANCZOS,
            )
        gray = ImageOps.autocontrast(gray)
        try:
            import cv2
            import numpy as np
        except ImportError:
            return gray
        thresholded = cv2.adaptiveThreshold(
            np.asarray(gray),
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            11,
        )
        return Image.fromarray(thresholded)

    @staticmethod
    def _prepare_for_mrz_ocr_glare(image: Image.Image, binarize: bool = False) -> Image.Image:
        """Suppress laminate glare: divide the band by its blurred background.

        A specular glare streak shifts local brightness far more than local
        contrast, so normalizing each pixel by the local background level
        leaves the dark MRZ strokes intact where thresholding wipes them out.
        Falls back to the soft grayscale prep when OpenCV is unavailable."""
        gray = ImageOps.grayscale(image)
        longest = max(gray.size)
        if 0 < longest < 2600:
            scale = min(2600 / longest, 4.0)
            gray = gray.resize(
                (max(1, round(gray.width * scale)), max(1, round(gray.height * scale))),
                Image.Resampling.LANCZOS,
            )
        try:
            import cv2
            import numpy as np
        except ImportError:
            return ImageOps.autocontrast(gray).filter(ImageFilter.SHARPEN)
        array = np.asarray(gray)
        background = cv2.GaussianBlur(array, (0, 0), 21)
        normalized = cv2.divide(array, background, scale=255)
        if binarize:
            # Global Otsu AFTER glare normalization keeps the "<" separators
            # crisp where local adaptive thresholding hallucinates letters.
            _, normalized = cv2.threshold(normalized, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return Image.fromarray(normalized)


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
        if os.environ.get("LALIGENCE_DEBUG_OCR"):
            # Local debugging only: dump the raw OCR text, candidate lines and
            # the selected TD3 pair so misreads can be reproduced offline.
            # Contains document PII -- never enable outside a private dev box.
            with open("/tmp/kyron_ocr_debug.txt", "w", encoding="utf-8") as handle:
                handle.write("RAW OCR TEXT:\n" + (ocr_text or "") + "\n\nCANDIDATE LINES:\n")
                handle.writelines(line + "\n" for line in lines)
                handle.write("\nSELECTED:\n" + (f"{selected[0]}\n{selected[1]}" if selected else "None") + "\n")
        if selected is None:
            evidence_score = self._passport_text_evidence_score(ocr_text or "")
            context.checks["passport_text_evidence_score"] = round(evidence_score, 3)
            if evidence_score >= 0.65:
                context.signals.append(_signal(
                    "MRZ_NOT_CONFIDENT",
                    "Passport MRZ could not be validated. Retake the photo with both MRZ lines fully visible, sharp, and with space below the document.",
                    "high",
                    0.78,
                ))
                context.checks["mrz_found"] = False
                context.checks["mrz_soft_fallback"] = True
                return OcrResult(confidence=0.0, mrz_valid=False, mrz_check_digits_valid=False)
            context.signals.append(_signal("MRZ_NOT_READ", "Passport MRZ was not read; upload must contain readable passport evidence.", "high", 0.82))
            context.checks["mrz_found"] = False
            context.checks["mrz_soft_fallback"] = False
            return OcrResult(confidence=0.0, mrz_valid=False, mrz_check_digits_valid=False)

        line1, line2, parsed = selected
        malaysian_single_identifier = (
            line1[2:5] == "MYS" and "<<" not in line1[5:]
        )
        if parsed.get("full_name") and not malaysian_single_identifier:
            parsed["full_name"] = self._corroborate_name_with_printed_fields(
                str(parsed["full_name"]),
                ocr_text or "",
            )
            printed_name_tokens = {
                token
                for source_line in (ocr_text or "").upper().splitlines()
                if "<" not in source_line
                for token in re.findall(r"[A-Z]{2,}", source_line)
            }
            printed_name_lines = [
                re.sub(r"[^A-Z]", "", source_line.upper())
                for source_line in (ocr_text or "").splitlines()
                if "<" not in source_line
            ]
            repaired_name_tokens = set(str(parsed["full_name"]).split())
            consensus_name = self._recover_name_from_mrz_consensus(
                lines,
                ocr_text or "",
                str(parsed.get("nationality") or ""),
            )
            if consensus_name and not (
                repaired_name_tokens
                and (
                    repaired_name_tokens.issubset(printed_name_tokens)
                    or all(
                        any(token in printed_line for printed_line in printed_name_lines)
                        for token in repaired_name_tokens
                    )
                )
            ):
                parsed["full_name"] = consensus_name
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
        # General TD3 fragments for non-Lao passports. A blurred MRZ may lose
        # its first characters while still exposing an issuer/name separator
        # and the digit-heavy data-line structure. Treat these as corroborating
        # passport evidence only; they never make ``mrz_valid`` true.
        if re.search(r"[A-Z]{3,5}[A-Z]{2,}<{1,3}[A-Z]{3,}", compact):
            score += 0.1
        if re.search(r"[A-Z0-9]{7,12}[A-Z0-9]{3}[A-Z0-9]{7}[MFNXWH][A-Z0-9]{6}", compact):
            score += 0.1
        return _clamp(score)

    @staticmethod
    def _corroborate_name_with_printed_fields(full_name: str, text: str) -> str:
        """Drop a trailing filler glyph when the printed name confirms it.

        MRZ OCR frequently turns the first ``<`` after a name into ``S``. The
        visual-zone OCR is independent evidence; only shorten a token when a
        non-MRZ printed line ends with the exact token minus that final glyph.
        """
        printed_lines = [
            re.sub(r"[^A-Z]", "", line.upper())
            for line in text.splitlines()
            if "<" not in line
        ]
        printed_tokens = {
            token
            for line in text.splitlines()
            if "<" not in line
            for token in re.findall(r"[A-Z]{2,}", line.upper())
            if token
            not in {
                "PASSPORT",
                "NATIONALITY",
                "AUTHORITY",
                "MINISTRY",
                "FOREIGN",
                "AFFAIRS",
                "COUNTRY",
                "DATE",
                "BIRTH",
                "EXPIRY",
                "ISSUE",
                "SEX",
            }
        }
        corrected: list[str] = []
        for token in full_name.split():
            # A "<" between two given names is often misread as a letter,
            # fusing them ("STEPHEN<WELCH" -> "STEPHENSWELCH"). Split at an
            # inner character only when a printed visual-zone line shows the
            # left chunk immediately followed by the right chunk's first
            # letter -- genuine names like VILAYSONE are never split because
            # print shows the same letter, not the next chunk, after "VILAY".
            fused_split = None
            for index in range(4, max(4, len(token) - 3)):
                left, glyph, right = token[:index], token[index], token[index + 1 :]
                if len(right) < 3 or right[0] == glyph:
                    continue
                if any(left + right[0] in line for line in printed_lines if len(line) > len(left)):
                    fused_split = (left, right)
                    break
            if fused_split:
                corrected.extend(fused_split)
                continue
            shortened = token[:-1]
            trailing_filler_removed = len(shortened) >= 4 and any(
                line.endswith(shortened) for line in printed_lines
            )
            corrected_token = shortened if trailing_filler_removed else token
            # Filler cleanup can remove the final character of a genuine name
            # when Tesseract repeats that same character throughout the MRZ
            # tail (``THOMAS...SSSS`` -> ``THOMA``). Restore exactly one letter
            # only when an independently OCR'd visual-zone line corroborates it.
            extensions = {
                line[-1]
                for line in printed_lines
                if len(token) >= 4 and len(line) > len(token) and line.endswith(token + line[-1])
            }
            if not trailing_filler_removed and len(extensions) == 1:
                corrected_token = token + extensions.pop()

            # Valid MRZ checks establish identity fields even when the name line
            # loses a few characters. Use the independently OCR'd visual zone to
            # repair only tightly bounded truncations: a printed token extending
            # the MRZ token, the MRZ token carrying one leading artifact, or a
            # near-exact OCR spelling. This turns ``KYU HID`` into ``YU HIDAKA``
            # without replacing unrelated names merely because both are words.
            candidates: list[tuple[int, int, float, str]] = []
            for printed in printed_tokens if corrected_token not in printed_tokens else ():
                similarity = SequenceMatcher(None, corrected_token, printed).ratio()
                prefix_extension = (
                    printed.startswith(corrected_token)
                    and 0 < len(printed) - len(corrected_token) <= 4
                    and similarity >= 0.65
                )
                leading_artifact = (
                    len(corrected_token) - len(printed) == 1
                    and corrected_token.endswith(printed)
                    and similarity >= 0.75
                )
                leading_truncation = (
                    len(printed) - len(corrected_token) == 1
                    and printed.endswith(corrected_token)
                    and similarity >= 0.75
                )
                single_substitution = (
                    len(corrected_token) == len(printed)
                    and len(printed) >= 5
                    and sum(left != right for left, right in zip(corrected_token, printed)) == 1
                )
                # The first/last filler beside a short surname can be read as a
                # letter at the same time that one real glyph is substituted
                # (Indian ``JHA`` -> MRZ OCR ``IHAK``). Permit that exact shape
                # only for short printed tokens: deleting one edge character
                # must leave a same-length token with at most one substitution.
                edge_filler_substitution = (
                    3 <= len(printed) <= 6
                    and len(corrected_token) == len(printed) + 1
                    and any(
                        sum(left != right for left, right in zip(trimmed, printed)) <= 1
                        for trimmed in (corrected_token[1:], corrected_token[:-1])
                    )
                )
                near_exact = similarity >= 0.86 and abs(len(printed) - len(corrected_token)) <= 2
                if prefix_extension or leading_artifact or leading_truncation or single_substitution or edge_filler_substitution or near_exact:
                    # A longer printed token that starts with the truncated MRZ
                    # token carries more information than a second OCR pass that
                    # repeats the same truncation (HIDA vs HIDAKA).
                    repair_priority = 3 if prefix_extension else 2 if (leading_artifact or leading_truncation or single_substitution or edge_filler_substitution) else 1
                    repair_detail = (
                        len(printed) - len(corrected_token)
                        if prefix_extension
                        else -abs(len(printed) - len(corrected_token))
                    )
                    candidates.append(
                        (
                            repair_priority,
                            repair_detail,
                            similarity,
                            printed,
                        )
                    )
            if candidates:
                corrected_token = max(candidates)[3]
            corrected.append(corrected_token)
        # OCR often prints adjacent given names without a space while the MRZ
        # correctly separates them with "<". If filler cleanup clipped at most
        # two trailing letters from the second token, restore them only when a
        # complete printed line is exactly the concatenation of the first name
        # and that slightly longer second name (TIMOTHY + GEO ->
        # TIMOTHYGEORG). This cannot pull labels or unrelated body text into the
        # identity name because the remainder must be a short direct extension.
        for index in range(len(corrected) - 1):
            left = corrected[index]
            right = corrected[index + 1]
            extensions = {
                line[len(left) :]
                for line in printed_lines
                if line.startswith(left)
                and line[len(left) :].startswith(right)
                and 0 < len(line[len(left) :]) - len(right) <= 2
                and len(line[len(left) :]) <= 20
            }
            if len(extensions) == 1:
                corrected[index + 1] = next(iter(extensions))

        # Visual-zone OCR usually prints surname and given name on consecutive
        # standalone lines. If one of a two-token MRZ name matches that pair
        # exactly, use the adjacent printed token to replace the other badly
        # damaged MRZ token. This is deliberately pair-based: a random place or
        # authority word elsewhere on the page cannot replace a name merely by
        # being alphabetic.
        if len(corrected) == 2:
            excluded_name_lines = {
                "PASSPORT",
                "NATIONALITY",
                "AUTHORITY",
                "MINISTRY",
                "FOREIGN",
                "AFFAIRS",
                "COUNTRY",
                "DATE",
                "BIRTH",
                "EXPIRY",
                "ISSUE",
                "SEX",
            }
            standalone_name_lines: list[str] = []
            for source_line in text.splitlines():
                if "<" in source_line or any(char.isdigit() for char in source_line):
                    continue
                words = re.findall(r"[A-Z]+", source_line.upper())
                # This repair is pair-based and expects the visual OCR's
                # surname and given name on separate lines. Exclude headings,
                # country phrases and mixed label/value rows instead of
                # flattening them into a plausible-looking long name.
                if len(words) != 1:
                    continue
                cleaned = words[0]
                if (
                    2 <= len(cleaned) <= 20
                    and cleaned not in excluded_name_lines
                    and cleaned not in MONTHS
                ):
                    standalone_name_lines.append(cleaned)
            mrz_source_lines = [
                re.sub(r"[^A-Z0-9<]", "", source_line.upper())
                for source_line in text.splitlines()
                if "<" in source_line
            ]
            pair_repairs: list[tuple[int, int, float, str, int]] = []
            for left, right in zip(standalone_name_lines, standalone_name_lines[1:]):
                pair = {left, right}
                exact = [index for index, token in enumerate(corrected) if token in pair]
                if len(pair) != 2 or len(exact) != 1 or len(corrected[exact[0]]) < 4:
                    continue
                # Both printed tokens must also occur in MRZ-bearing OCR. This
                # excludes adjacent body-text noise such as OVER/HUNEN... while
                # retaining the independently seen surname/given-name pair.
                def mrz_supports(token: str) -> bool:
                    if any(token in line for line in mrz_source_lines):
                        return True
                    if len(token) > 6:
                        return False
                    return any(
                        sum(left_char != right_char for left_char, right_char in zip(sample, token)) <= 2
                        for line in mrz_source_lines
                        for width in {len(token), len(token) + 1}
                        for start in range(max(0, len(line) - width + 1))
                        for sample in (line[start : start + width].strip("<")[: len(token)],)
                        if len(sample) == len(token) and sample.isalpha()
                    )

                if not all(mrz_supports(token) for token in pair):
                    continue
                missing = next(iter(pair - {corrected[exact[0]]}))
                if len(missing) < 3:
                    continue
                other_index = 1 - exact[0]
                # Do not degrade an identity token already supported by both
                # the visual zone and an MRZ-bearing OCR pass. A single clean
                # visual read is enough when the MRZ independently agrees;
                # nearby page text such as OVER must not displace that name.
                current_other = corrected[other_index]
                if (
                    current_other in standalone_name_lines
                    and any(current_other in line for line in mrz_source_lines)
                ):
                    continue
                if corrected[other_index] not in pair:
                    pair_repairs.append(
                        (
                            len(corrected[exact[0]]),
                            len(missing),
                            SequenceMatcher(None, corrected[other_index], missing).ratio(),
                            missing,
                            other_index,
                        )
                    )
            if pair_repairs:
                _, _, _, missing, other_index = max(pair_repairs)
                corrected[other_index] = missing
        return " ".join(corrected)

    @staticmethod
    def _recover_name_from_mrz_consensus(
        lines: list[str],
        text: str,
        nationality: str,
    ) -> str | None:
        """Recover a split name only when independent OCR reads agree.

        On low-light identity pages, the surname/given-name ``<<`` separator
        can become letters in some OCR passes. A different pass often retains
        enough of the separator, while visual-zone OCR reads the printed given
        name clearly. Require two country-matched MRZ candidates plus that
        independent printed token to share the same surname prefix before
        replacing the selected candidate's name.
        """
        if len(nationality) != 3 or not nationality.isalpha():
            return None

        excluded = {
            "PASSPORT",
            "NATIONALITY",
            "AUTHORITY",
            "MINISTRY",
            "FOREIGN",
            "AFFAIRS",
            "COUNTRY",
            "DATE",
            "BIRTH",
            "EXPIRY",
            "ISSUE",
            "SEX",
            "JAPAN",
            "DOCUMENT",
            "NUMBER",
        }
        printed_tokens = {
            token
            for source_line in text.upper().splitlines()
            if "<" not in source_line
            for token in re.findall(r"[A-Z]{4,20}", source_line)
            if token not in excluded
        }
        if not printed_tokens:
            return None

        name_lines = [
            line
            for line in lines
            if len(line) == 44
            and line.startswith("P")
            and line[2:5] == nationality
            and "<<" in line[5:]
        ]
        best: tuple[int, float, int, str] | None = None
        for printed in printed_tokens:
            prefixes: set[str] = set()
            similarities: list[float] = []
            for line in name_lines:
                field = line[5:]
                candidate_best: tuple[float, int, int] | None = None
                min_width = max(4, len(printed) - 2)
                max_width = min(len(field), len(printed) + 2)
                for start in range(min(20, len(field))):
                    for width in range(min_width, max_width + 1):
                        sample = field[start : start + width].strip("<")
                        if len(sample) < 4 or not sample.isalpha():
                            continue
                        similarity = SequenceMatcher(None, sample, printed).ratio()
                        candidate = (similarity, -abs(len(sample) - len(printed)), start)
                        if candidate_best is None or candidate > candidate_best:
                            candidate_best = candidate
                if candidate_best is None or candidate_best[0] < 0.84:
                    continue
                start = candidate_best[2]
                prefix = re.sub(r"[^A-Z]", "", field[:start])
                if 4 <= len(prefix) <= 20:
                    prefixes.add(prefix)
                    similarities.append(candidate_best[0])

            if len(prefixes) < 2:
                continue
            surname = os.path.commonprefix(sorted(prefixes)).rstrip("<")
            if len(surname) < 4 or not surname.isalpha():
                continue
            average_similarity = sum(similarities) / len(similarities)
            candidate = (
                len(prefixes),
                average_similarity,
                len(surname),
                f"{printed} {surname}",
            )
            if best is None or candidate > best:
                best = candidate
        return best[3] if best else None

    @staticmethod
    def _candidate_lines(text: str) -> list[str]:
        lines: list[str] = []
        normalized_fragments: list[str] = []
        visual_source_lines = [
            source_line.upper()
            for source_line in text.splitlines()
            if "<" not in source_line
        ]
        visible_country_codes = {
            token
            for source_line in visual_source_lines
            for token in re.findall(r"(?<![A-Z])[A-Z]{3}(?![A-Z])", source_line)
            if token not in MONTHS
            and token not in {"AND", "THE", "SEX", "EXP", "DOB", "MRZ"}
        }
        printed_country_names = {
            "AUSTRALIA": "AUS",
            "JAPAN": "JPN",
            "KINGDOM OF THAILAND": "THA",
            "THAILAND": "THA",
            "LAO PDR": "LAO",
            "LAOS": "LAO",
            "UNITED STATES OF AMERICA": "USA",
            "UNITED STATES": "USA",
            "REPUBLIC OF KOREA": "KOR",
            "SOUTH KOREA": "KOR",
            "SPAIN": "ESP",
            "FRANCE": "FRA",
            "CANADA": "CAN",
            "REPUBLIC OF INDIA": "IND",
            "INDIA": "IND",
            "PEOPLE'S REPUBLIC OF CHINA": "CHN",
        }
        for source_line in visual_source_lines:
            visible_country_codes.update(
                code
                for country_name, code in printed_country_names.items()
                if country_name in source_line
            )
        nat_table = str.maketrans(
            {"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "4": "A", "6": "G"}
        )
        visible_document_fragments = {
            token
            for source_line in text.upper().splitlines()
            if "<" not in source_line
            for token in re.findall(r"(?<![A-Z0-9])[A-Z0-9]{4,9}(?![A-Z0-9])", source_line)
            if sum(char.isdigit() for char in token) >= 3
            and any(char.isalpha() for char in token)
        }
        # Visual OCR commonly preserves a Lao passport number as two tokens
        # (``PA 0490616``). Join only the country-specific PA prefix and a
        # six/seven-digit OCR-like suffix; generic labels such as ``NO`` must
        # never become document-number evidence.
        printed_number_digit_map = str.maketrans(
            {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "G": "6", "B": "8"}
        )
        for source_line in visual_source_lines:
            for match in re.finditer(
                r"(?<![A-Z0-9])(P[A-Z])\s+([0-9OQDILZSBG]{6,7})(?![A-Z0-9])",
                source_line,
            ):
                suffix = match.group(2).translate(printed_number_digit_map)
                joined = match.group(1) + suffix
                if len(joined) in {8, 9} and suffix.isdigit():
                    visible_document_fragments.add(joined)
        # TD3 allocates nine characters to the document-number field, but many
        # countries print an eight-character passport number and pad the MRZ
        # field with ``<``. Preserve both full-width and padded visual reads.
        visible_document_numbers = {
            token if len(token) == 9 else f"{token}<"
            for token in visible_document_fragments
            if len(token) in {8, 9}
        }
        visible_name_tokens = {
            cleaned
            for source_line in visual_source_lines
            for cleaned in [re.sub(r"[^A-Z]", "", source_line)]
            if 3 <= len(cleaned) <= 20
            and cleaned
            not in {
                "PASSPORT",
                "NATIONALITY",
                "AUTHORITY",
                "MINISTRY",
                "FOREIGN",
                "AFFAIRS",
                "COUNTRY",
                "DATE",
                "BIRTH",
                "EXPIRY",
                "ISSUE",
                "SEX",
            }
            and cleaned not in MONTHS
        }

        def add_candidate(candidate: str) -> None:
            candidate = MrzAnalyzer._normalize_ocr_mrz_line(candidate)
            candidate = MrzAnalyzer._recover_short_td3_line(candidate)
            if not candidate:
                return
            candidate = candidate[:44].ljust(44, "<")
            if MRZ_ALLOWED.match(candidate) and candidate not in lines:
                lines.append(candidate)

        for line in text.upper().splitlines():
            normalized = re.sub(r"[^A-Z0-9<]", "", line)
            if normalized:
                normalized_fragments.append(normalized)
            add_candidate(normalized)
            # A soft rotated pass can preserve the issuer and both names while
            # dropping one of the two surname/given-name separators
            # (``PSINDIMAK<ASHUTOSH...``). Restore exactly one chevron only when
            # the independent visual zone prints the token immediately after
            # that separator. The paired data line must still pass every ICAO
            # check before this name line can be selected.
            single_separator = normalized.find("<", 5)
            if (
                len(normalized) >= 20
                and normalized.startswith("P")
                and normalized[2:5].isalpha()
                and "<<" not in normalized
                and 7 <= single_separator <= 25
                and any(
                    normalized[single_separator + 1 :].startswith(token)
                    for token in visible_name_tokens
                    if len(token) >= 4
                )
            ):
                add_candidate(
                    normalized[:single_separator]
                    + "<<"
                    + normalized[single_separator + 1 :]
                )
            # A page edge can be inserted between the document marker and a
            # genuine two-letter type (PRPAUS... instead of PPAUS...). Remove
            # exactly that one glyph only when the resulting issuer is
            # independently confirmed by the printed country name/code.
            if (
                len(normalized) >= 12
                and normalized[0] == "P"
                and normalized[2] == "P"
                and normalized[3:6] in visible_country_codes
                and "<<" in normalized[6:]
            ):
                add_candidate(normalized[0] + normalized[2:])
        for index, fragment in enumerate(normalized_fragments[:-1]):
            add_candidate(fragment + normalized_fragments[index + 1])

        # Keep document numbers from the original data-line candidates before
        # adding any repairs. A low-resolution OCR pass may read the number
        # cleanly but damage a date, while another pass reads the dates cleanly
        # and changes one number glyph (RB... -> 9B...). The number's own ICAO
        # check digit lets the clean pass safely corroborate the second one.
        original_checked_document_numbers = {
            candidate[:9]
            for candidate in lines
            if len(candidate) >= 13
            and candidate[9].isdigit()
            and MrzAnalyzer._check_digit(candidate[:9]) == candidate[9]
        }

        # Low-resolution phone photos often split TD3 line 2 differently in
        # each OCR pass: one pass preserves the document number and its check
        # digit, while another drops that prefix but reads the protected
        # birth/sex/expiry segment clearly. Fuse those independent observations
        # only when the name line corroborates the issuer and all three primary
        # ICAO checks validate after normalization. This recovers evidence; it
        # does not invent unchecked identity fields.
        name_line_issuers = {
            candidate[2:5]
            for candidate in lines
            if candidate.startswith("P")
            and "<<" in candidate[5:]
            and candidate[2:5].isalpha()
        }
        checked_numbers_by_issuer = {
            issuer: {
                candidate[:9]
                for candidate in lines
                if len(candidate) >= 13
                and candidate[9].isdigit()
                and sum(
                    observed != expected
                    for observed, expected in zip(candidate[10:13], issuer)
                ) <= 1
                and MrzAnalyzer._check_digit(candidate[:9]) == candidate[9]
            }
            for issuer in name_line_issuers
        }
        stitched_data_lines: list[str] = []
        if name_line_issuers:
            for fragment in normalized_fragments:
                for start in range(max(0, len(fragment) - 14)):
                    segment = fragment[start : start + 31]
                    if len(segment) < 15 or segment[7] not in {"M", "F", "N", "X", "W", "H"}:
                        continue
                    for issuer in name_line_issuers:
                        for document_number in checked_numbers_by_issuer.get(issuer, set()):
                            document_check = MrzAnalyzer._check_digit(document_number)
                            line1 = f"P<{issuer}HOLDER<<TEST".ljust(44, "<")
                            line2 = (
                                document_number
                                + document_check
                                + issuer
                                + segment[:31].ljust(31, "<")
                            )
                            parsed = MrzAnalyzer()._parse_td3(line1, line2)
                            if (
                                parsed.get("valid")
                                and parsed.get("document_check_digit_valid") is True
                                and parsed.get("birth_check_digit_valid") is True
                                and parsed.get("expiry_check_digit_valid") is True
                            ):
                                stitched_data_lines.append(line2)
        for stitched in stitched_data_lines:
            add_candidate(stitched)

        # Correct a one-character OCR error in the issuing-country/nationality
        # field only when the same three-letter code was independently read in
        # the visual inspection zone. This is especially useful on dark Japanese
        # passports where JPN is commonly rendered as IPN/5PN in the MRZ.
        country_repaired_lines: list[str] = []
        country_replaced_lines: set[str] = set()
        corroborated_country_codes = visible_country_codes | name_line_issuers
        for candidate in lines:
            country_start: int | None = None
            if candidate.startswith("P") and "<<" in candidate:
                country_start = 2
            elif sum(char.isdigit() for char in candidate) >= 8:
                country_start = 10
            if country_start is None:
                continue
            observed = candidate[country_start : country_start + 3]
            translated_observed = observed.translate(nat_table)
            # Do not replace a country code that was independently read exactly
            # in the visual inspection zone. Without this guard, a noisy token
            # such as SUS could overwrite a clean AUS MRZ field merely because
            # it is one character away.
            if observed in corroborated_country_codes or translated_observed in corroborated_country_codes:
                continue
            repairs = {
                code
                for code in corroborated_country_codes
                # Nationality is not protected by its own check digit. OCR
                # commonly emits a digit look-alike first (IND -> 1ND), then a
                # second pass changes one remaining letter (1ND -> 14D). Apply
                # the standard digit-to-letter translation before measuring
                # the one-glyph difference. The printed country name/code or a
                # separately read TD3 name-line issuer is independent evidence,
                # while the paired data line still has to satisfy every ICAO
                # checksum before it can be accepted.
                if sum(
                    left != right
                    for left, right in zip(translated_observed, code)
                ) == 1
            }
            if len(repairs) == 1:
                code = next(iter(repairs))
                country_replaced_lines.add(candidate)
                country_repaired_lines.append(
                    candidate[:country_start] + code + candidate[country_start + 3 :]
                )
        lines[:] = [line for line in lines if line not in country_replaced_lines]
        for repaired in country_repaired_lines:
            add_candidate(repaired)

        # A rotated or softly focused MRZ often yields complementary reads:
        # one pass preserves a printed prefix (``B729...``), while another
        # preserves the complete TD3 data line but confuses an alphanumeric
        # document glyph (``B`` -> ``8``) or its adjacent check digit. Recover
        # a document number only when all of the following independently agree:
        #   * a visual-zone fragment of at least four leading characters;
        #   * at most one OCR-lookalike substitution in the MRZ field; and
        #   * the document, birth, expiry, optional-data and composite ICAO
        #     check digits all validate after the repair.
        # The composite check includes the repaired document check digit, so a
        # plausible-looking visual token alone cannot create a valid identity.
        if visible_document_fragments:
            reverse_document_confusions = {
                "0": ("O", "Q", "D"),
                "1": ("I", "L"),
                "2": ("Z",),
                "3": ("S", "B"),
                "4": ("A",),
                "5": ("S",),
                "6": ("G",),
                "7": ("T", "Z"),
                "8": ("B",),
                "9": ("G",),
            }
            consensus_document_lines: list[str] = []
            document_number_hypotheses: set[str] = set()
            for candidate in list(lines):
                if len(candidate) != 44 or sum(char.isdigit() for char in candidate) < 8:
                    continue
                observed_number = candidate[:9]
                number_candidates = {observed_number}
                for index, char in enumerate(observed_number):
                    alternatives = list(reverse_document_confusions.get(char, ()))
                    if char.isalpha():
                        alternatives.extend(MrzAnalyzer._DIGIT_ALTERNATIVES.get(char, ())[:1])
                    for replacement in alternatives:
                        number_candidates.add(
                            observed_number[:index]
                            + replacement
                            + observed_number[index + 1 :]
                        )

                # Keep a uniquely corroborated number even when this OCR pass
                # damaged the adjacent nationality/date tail. A second pass may
                # contain the protected 35-character tail intact.
                ranked_numbers = sorted(
                    (
                        max(
                            (
                                len(fragment)
                                for fragment in visible_document_fragments
                                if number.rstrip("<").startswith(fragment)
                            ),
                            default=0,
                        ),
                        -sum(
                            left != right
                            for left, right in zip(observed_number, number)
                        ),
                        number,
                    )
                    for number in number_candidates
                )
                if ranked_numbers and ranked_numbers[-1][0] >= 4:
                    best_number_key = ranked_numbers[-1][:2]
                    best_numbers = {
                        number
                        for prefix, substitutions, number in ranked_numbers
                        if (prefix, substitutions) == best_number_key
                    }
                    if len(best_numbers) == 1:
                        document_number_hypotheses.add(next(iter(best_numbers)))

                ranked_repairs: list[tuple[int, int, str]] = []
                for document_number in number_candidates:
                    expected_check = MrzAnalyzer._check_digit(document_number)
                    repaired = document_number + expected_check + candidate[10:]
                    issuer = candidate[10:13].translate(nat_table)
                    if not issuer.isalpha():
                        issuer = "UTO"
                    parsed = MrzAnalyzer()._parse_td3(
                        f"P<{issuer}HOLDER<<TEST".ljust(44, "<"),
                        repaired,
                    )
                    if not (
                        parsed.get("valid")
                        and parsed.get("document_check_digit_valid") is True
                        and parsed.get("birth_check_digit_valid") is True
                        and parsed.get("expiry_check_digit_valid") is True
                        and parsed.get("optional_check_digit_valid") is True
                        and parsed.get("composite_check_digit_valid") is True
                    ):
                        continue
                    visible_prefix = max(
                        (
                            len(fragment)
                            for fragment in visible_document_fragments
                            if document_number.rstrip("<").startswith(fragment)
                        ),
                        default=0,
                    )
                    if visible_prefix < 4:
                        continue
                    substitutions = sum(
                        left != right
                        for left, right in zip(observed_number, document_number)
                    )
                    ranked_repairs.append((visible_prefix, -substitutions, repaired))

                if ranked_repairs:
                    ranked_repairs.sort(reverse=True)
                    best_key = ranked_repairs[0][:2]
                    best_lines = {
                        repaired
                        for prefix, substitutions, repaired in ranked_repairs
                        if (prefix, substitutions) == best_key
                    }
                    if len(best_lines) == 1:
                        consensus_document_lines.append(next(iter(best_lines)))
            for repaired in consensus_document_lines:
                add_candidate(repaired)

            # Stitch a uniquely corroborated document number to a complete
            # check-digit-protected tail from another OCR pass. The tail starts
            # at the document check digit and is exactly 35 TD3 characters.
            # Requiring every ICAO checksum, including optional and composite,
            # prevents an arbitrary 35-character body-text run from qualifying.
            stitched_consensus_lines: list[str] = []
            consensus_fragments = list(normalized_fragments)
            consensus_fragments.extend(
                left + right
                for left, right in zip(
                    normalized_fragments,
                    normalized_fragments[1:],
                )
            )
            for fragment in consensus_fragments:
                normalized = MrzAnalyzer._normalize_ocr_mrz_line(fragment)
                for start in range(max(0, len(normalized) - 34)):
                    tail = normalized[start : start + 35]
                    if len(tail) != 35 or not tail[0].isdigit():
                        continue
                    issuer = tail[1:4].translate(nat_table)
                    if not issuer.isalpha():
                        continue
                    for document_number in document_number_hypotheses:
                        stitched = document_number + tail
                        parsed = MrzAnalyzer()._parse_td3(
                            f"P<{issuer}HOLDER<<TEST".ljust(44, "<"),
                            stitched,
                        )
                        if (
                            parsed.get("valid")
                            and parsed.get("document_check_digit_valid") is True
                            and parsed.get("birth_check_digit_valid") is True
                            and parsed.get("expiry_check_digit_valid") is True
                            and parsed.get("optional_check_digit_valid") is True
                            and parsed.get("composite_check_digit_valid") is True
                        ):
                            stitched_consensus_lines.append(stitched)
            for stitched in stitched_consensus_lines:
                add_candidate(stitched)

            # Some softly focused Lao captures preserve the protected
            # nationality/date segment and final composite digit, but split or
            # corrupt the document-number prefix. Fuse that segment with an
            # independently read printed PA number only when the optional-data
            # area is visibly filler-like and the observed trailing glyph
            # agrees with the recomputed ICAO composite digit. This keeps the
            # recovery strict: a missing or wrong composite digit cannot pass.
            lao_consensus_lines: list[str] = []
            trailing_digit_map = {
                "O": "0", "Q": "0", "D": "0",
                "I": "1", "L": "1",
                "Z": "2", "S": "5", "B": "8",
                "G": "6", "T": "7", "E": "8", "A": "4",
            }
            filler_like = set("<KCER")
            lao_numbers = {
                number
                for number in visible_document_numbers
                if number.startswith("PA")
            }
            protected_lao_candidates: list[tuple[str, str]] = []
            for fragment in consensus_fragments:
                normalized = MrzAnalyzer._normalize_ocr_mrz_line(fragment)
                for issuer in corroborated_country_codes & {"LAO"}:
                    issuer_start = normalized.find(issuer)
                    while issuer_start >= 0:
                        payload = normalized[issuer_start + 3 :]
                        if len(payload) >= 15:
                            protected_core = payload[:15]
                            remainder = payload[15:]
                            filler_count = sum(char in filler_like for char in remainder)
                            non_filler_count = sum(
                                char not in filler_like
                                for char in remainder[:-1]
                            )
                            if protected_core[7:8] in {"M", "F", "N", "H", "W", "<"}:
                                for document_number in lao_numbers:
                                    document_check = MrzAnalyzer._check_digit(document_number)
                                    provisional = (
                                        document_number
                                        + document_check
                                        + issuer
                                        + protected_core
                                        + ("<" * 16)
                                    )[:44]
                                    line1 = f"P<{issuer}HOLDER<<TEST".ljust(44, "<")
                                    _, normalized_line = MrzAnalyzer._normalize_td3_fields(
                                        line1,
                                        provisional,
                                    )
                                    primary_probe = normalized_line[:43] + "<"
                                    primary_parsed = MrzAnalyzer()._parse_td3(
                                        line1,
                                        primary_probe,
                                    )
                                    if not (
                                        primary_parsed.get("document_check_digit_valid") is True
                                        and primary_parsed.get("birth_check_digit_valid") is True
                                        and primary_parsed.get("expiry_check_digit_valid") is True
                                    ):
                                        continue
                                    protected_lao_candidates.append(
                                        (line1, normalized_line)
                                    )
                                    if filler_count < 6 or non_filler_count > 2:
                                        continue
                                    composite = MrzAnalyzer._check_digit(
                                        normalized_line[:10]
                                        + normalized_line[13:20]
                                        + normalized_line[21:43]
                                    )
                                    observed_tail_digits = {
                                        trailing_digit_map.get(char, char)
                                        for char in remainder[-4:]
                                        if char.isdigit() or char in trailing_digit_map
                                    }
                                    if composite not in observed_tail_digits:
                                        continue
                                    repaired = normalized_line[:43] + composite
                                    parsed = MrzAnalyzer()._parse_td3(line1, repaired)
                                    if (
                                        parsed.get("valid")
                                        and parsed.get("document_check_digit_valid") is True
                                        and parsed.get("birth_check_digit_valid") is True
                                        and parsed.get("expiry_check_digit_valid") is True
                                        and parsed.get("composite_check_digit_valid") is True
                                    ):
                                        lao_consensus_lines.append(repaired)
                        issuer_start = normalized.find(issuer, issuer_start + 1)

            # A second OCR pass may carry the long filler run and final
            # composite glyph while changing one expiry digit. Match it to the
            # exact, primary-check-valid core above by birth/check/sex and by a
            # near-identical expiry field. The final composite must still be
            # visible in this independent pass.
            for line1, normalized_line in protected_lao_candidates:
                birth_sex = normalized_line[13:21]
                expected_expiry = normalized_line[21:28]
                composite = MrzAnalyzer._check_digit(
                    normalized_line[:10]
                    + normalized_line[13:20]
                    + normalized_line[21:43]
                )
                for evidence in consensus_fragments:
                    evidence = MrzAnalyzer._normalize_ocr_mrz_line(evidence)
                    anchor = evidence.find(birth_sex)
                    if anchor < 0 or len(evidence) < anchor + 15:
                        continue
                    observed_expiry = evidence[anchor + 8 : anchor + 15]
                    observed_expiry = "".join(
                        trailing_digit_map.get(char, char)
                        for char in observed_expiry
                    )
                    if sum(
                        left != right
                        for left, right in zip(observed_expiry, expected_expiry)
                    ) > 1:
                        continue
                    remainder = evidence[anchor + 15 :]
                    if sum(char in filler_like for char in remainder) < 6:
                        continue
                    observed_tail_digits = {
                        trailing_digit_map.get(char, char)
                        for char in remainder[-4:]
                        if char.isdigit() or char in trailing_digit_map
                    }
                    if composite not in observed_tail_digits:
                        continue
                    repaired = normalized_line[:43] + composite
                    parsed = MrzAnalyzer()._parse_td3(line1, repaired)
                    if (
                        parsed.get("valid")
                        and parsed.get("document_check_digit_valid") is True
                        and parsed.get("birth_check_digit_valid") is True
                        and parsed.get("expiry_check_digit_valid") is True
                        and parsed.get("composite_check_digit_valid") is True
                    ):
                        lao_consensus_lines.append(repaired)
            for repaired in lao_consensus_lines:
                add_candidate(repaired)

            # Document-number consensus can create its strongest data-line
            # candidate after the first nationality-repair pass above. Re-run
            # the same narrowly bounded reconciliation on those late lines.
            # This is required when one pass preserves every checksum but reads
            # IND as 14D, while a separate name-line pass preserves issuer IND.
            late_country_repairs: list[str] = []
            for candidate in list(lines):
                if len(candidate) != 44 or sum(char.isdigit() for char in candidate) < 8:
                    continue
                observed = candidate[10:13]
                translated_observed = observed.translate(nat_table)
                if translated_observed in corroborated_country_codes:
                    continue
                repairs = {
                    code
                    for code in corroborated_country_codes
                    if sum(
                        left != right
                        for left, right in zip(translated_observed, code)
                    ) == 1
                }
                if len(repairs) == 1:
                    code = next(iter(repairs))
                    late_country_repairs.append(
                        candidate[:10] + code + candidate[13:]
                    )
            for repaired in late_country_repairs:
                add_candidate(repaired)

        # A sharp visual-zone passport number is useful independent evidence
        # when OCR changes one printed MRZ digit into another (for example the
        # Japanese number TT1414449 read as TT4414449). Generate every one-digit
        # repair allowed by the MRZ's own document-number check digit, then use
        # the visible number only when it identifies a unique candidate within
        # one character. This cannot validate a number merely because it looks
        # plausible; the embedded check digit remains mandatory.
        if visible_document_numbers:
            repaired_data_lines: list[str] = []
            for candidate in lines:
                if len(candidate) < 13 or not candidate[9].isdigit():
                    continue
                document_number = candidate[:9]
                if MrzAnalyzer._check_digit(document_number) == candidate[9]:
                    continue
                exact_visual_matches = {
                    visible
                    for visible in visible_document_numbers
                    if MrzAnalyzer._check_digit(visible) == candidate[9]
                    and sum(
                        left != right
                        for left, right in zip(document_number, visible)
                    )
                    <= 1
                }
                if len(exact_visual_matches) == 1:
                    repaired_data_lines.append(
                        next(iter(exact_visual_matches)) + candidate[9:]
                    )
                    continue
                repairs: set[str] = set()
                for index, char in enumerate(document_number):
                    if not char.isdigit():
                        continue
                    for replacement in "0123456789":
                        if replacement == char:
                            continue
                        repaired = (
                            document_number[:index]
                            + replacement
                            + document_number[index + 1 :]
                        )
                        if MrzAnalyzer._check_digit(repaired) == candidate[9]:
                            repairs.add(repaired)
                ranked = sorted(
                    (
                        sum(left != right for left, right in zip(repair, visible)),
                        repair,
                    )
                    for repair in repairs
                    for visible in visible_document_numbers
                )
                if not ranked or ranked[0][0] > 1:
                    continue
                best_distance = ranked[0][0]
                best_repairs = {
                    repair for distance, repair in ranked if distance == best_distance
                }
                if len(best_repairs) == 1:
                    repaired_data_lines.append(
                        next(iter(best_repairs)) + candidate[9:]
                    )
            for repaired in repaired_data_lines:
                add_candidate(repaired)

        if original_checked_document_numbers:
            consensus_repaired_lines: list[str] = []
            for candidate in list(lines):
                if len(candidate) < 13 or not candidate[9].isdigit():
                    continue
                observed = candidate[:9]
                if MrzAnalyzer._check_digit(observed) == candidate[9]:
                    continue
                ranked = sorted(
                    (
                        sum(left != right for left, right in zip(observed, checked)),
                        checked,
                    )
                    for checked in original_checked_document_numbers
                    if MrzAnalyzer._check_digit(checked) == candidate[9]
                )
                if not ranked or ranked[0][0] > 2:
                    continue
                best_distance = ranked[0][0]
                best_numbers = {
                    checked for distance, checked in ranked if distance == best_distance
                }
                if len(best_numbers) == 1:
                    consensus_repaired_lines.append(
                        next(iter(best_numbers)) + candidate[9:]
                    )
            for repaired in consensus_repaired_lines:
                add_candidate(repaired)

        # On otherwise readable low-resolution passports, OCR can omit the
        # small ``P<`` prefix while preserving the issuing country and the full
        # name line (``USAWILLIAMS<<...``). Recover that prefix only when a
        # digit-heavy TD3 data-line candidate independently supplies the same
        # three-letter nationality. The reconstructed line must still pair with
        # that data line and pass the ICAO check digits in ``_select_td3_pair``.
        issuer_votes: dict[str, int] = {}
        for candidate in lines:
            if len(candidate) >= 13 and sum(char.isdigit() for char in candidate) >= 8:
                issuer = candidate[10:13].translate(nat_table)
                if issuer.isalpha():
                    issuer_votes[issuer] = issuer_votes.get(issuer, 0) + 1

        if issuer_votes:
            max_votes = max(issuer_votes.values())
            likely_issuers = {
                issuer for issuer, votes in issuer_votes.items() if votes == max_votes
            }
            for fragment in normalized_fragments:
                normalized = MrzAnalyzer._normalize_ocr_mrz_line(fragment)
                for issuer in likely_issuers:
                    issuer_index = normalized.find(issuer, 0, 5)
                    if issuer_index < 0:
                        near_matches = [
                            index
                            for index in range(min(3, max(0, len(normalized) - 2)))
                            if normalized[index : index + 3].isalpha()
                            and sum(
                                left != right
                                for left, right in zip(
                                    normalized[index : index + 3], issuer
                                )
                            )
                            == 1
                        ]
                        issuer_index = near_matches[0] if len(near_matches) == 1 else -1
                    if issuer_index < 0:
                        continue
                    # The issuer is supplied by line-2 consensus; retain only
                    # the name text after the noisy issuer glyphs. Digits are
                    # impossible in a TD3 name field and represent misread
                    # filler chevrons, so normalize them back to fillers.
                    suffix = issuer + normalized[issuer_index + 3 :]
                    suffix = "".join("<" if char.isdigit() else char for char in suffix)
                    separator = suffix.find("<<", 3)
                    if separator < 0:
                        # One of the two separator chevrons is commonly lost on
                        # a dark MRZ. Promote a plausible single separator only
                        # after line-2 consensus supplied the issuer; pairing and
                        # check-digit validation remain mandatory downstream.
                        single_separator = suffix.find("<", 6, 25)
                        if single_separator >= 6:
                            suffix = (
                                suffix[:single_separator]
                                + "<<"
                                + suffix[single_separator + 1 :]
                            )
                            separator = single_separator
                    if (
                        len(suffix) < 18
                        or separator < 6
                    ):
                        continue
                    add_candidate(f"P<{suffix}")
        return lines

    @staticmethod
    def _normalize_ocr_mrz_line(line: str) -> str:
        if not line:
            return line
        # A border, page edge, or security glyph can be joined to the TD3 type
        # marker (for example ``7P<THA...`` or ``BP<THA...``). The embedded
        # ``P<`` marker is unambiguous near the start, so discard only the one
        # or two leading OCR artifacts before normal field normalization.
        td3_marker = line.find("P<", 0, 4)
        if td3_marker > 0:
            line = line[td3_marker:]
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
        # Two-letter document types (Korean "PM", Lao "PO", diplomatic "PD")
        # produce a clean name line that is not "P<...". Keep it when it has the
        # TD3 shape: P + type letter + 3-letter country + a "<<" name separator
        # and essentially no digits (a name line, not the data line). Blurred
        # filler glyphs at the end of a genuine name line can occasionally be
        # read as a short digit run (for example ``...<S<98``). Keep that narrow
        # case only when every digit follows the surname separator; the paired
        # data line must still pass its ICAO check digits before MRZ validation.
        separator = line.find("<<", 5)
        digit_positions = [index for index, char in enumerate(line) if char.isdigit()]
        tolerable_tail_digits = (
            separator >= 5
            and len(digit_positions) <= 3
            and all(index > separator for index in digit_positions)
        )
        if (
            len(line) >= 20
            and line[0] == "P"
            and "A" <= line[1] <= "Z"
            and line[2:5].isalpha()
            and separator >= 5
            and (len(digit_positions) <= 1 or tolerable_tail_digits)
        ):
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

    @staticmethod
    def _filler_letters(line1: str) -> set[str]:
        """The letters an OCR engine is substituting for MRZ filler "<" in this
        image. Two independent cues on TD3 line 1's filler zone:
        - a letter repeating heavily (>=3x) in the deep tail, when the whole run
          was misread (e.g. "KKKKKKSSSS" instead of "<<<<<<<<<<");
        - short letter "islands" (1-2 chars) stranded between "<" characters
          (e.g. "<<S<<<S<"), when only some fillers were misread -- a genuine
          name token never floats alone inside the filler run.
        Empty for a cleanly-read line."""
        letters: set[str] = set()
        counts: dict[str, int] = {}
        for ch in line1[24:44]:
            if "A" <= ch <= "Z":
                counts[ch] = counts.get(ch, 0) + 1
        letters.update(letter for letter, n in counts.items() if n >= 3)
        # A filler island is a 1-2 letter run followed by a filler run ("<<").
        # Exception: when that "<<" is the primary surname/given separator
        # itself, the letters are a genuine surname suffix ("WALKER<JR<<"),
        # not filler -- skip only that one position.
        field = line1[5:44]
        separator = field.find("<<")
        for island in re.finditer(r"(?<=<)([A-Z]{1,2})(?=<<)", field):
            if island.end(1) == separator:
                continue
            letters.update(island.group(1))
        return letters

    @staticmethod
    def _extract_mrz_names(line1: str, nationality: str | None = None) -> tuple[str, str]:
        """Extract surname and given names from TD3 line 1, robust to OCR that
        renders the "<" filler as letters. Filler-substitute letters come in two
        confidence tiers:
        - STRONG (may clip a name's trailing letter): the single dominant tail
          letter, island letters stranded inside "<" runs, and letters absorbed
          from inside filler runs -- each is direct evidence of substitution.
        - WEAK (collapse runs only, never touch a name): tail letters without
          clear dominance, e.g. an E that shows up in mixed tail garbage must
          not eat the genuine E ending "KHATTHAPHONE"."""
        # Anchor the name-field start. Normally position 5 (after "P", the type
        # and the 3-letter country), but OCR can eat prefix characters and shift
        # the names left ("POLAOSENGVILAY" read as "P<AOSENGVILAY" would lose
        # the S). Line 2's nationality is the same code as the line-1 issuer,
        # so use it to locate the true boundary.
        start = 5
        if nationality:
            found = line1.find(nationality, 1, 8)
            if found != -1:
                start = found + 3
            elif line1[2:5] != nationality and line1[2:4] == nationality[1:]:
                start = 4
        field = line1[start:44]

        counts: dict[str, int] = {}
        for ch in line1[24:44]:
            if "A" <= ch <= "Z":
                counts[ch] = counts.get(ch, 0) + 1
        tail_letters = {letter for letter, n in counts.items() if n >= 3}
        strong: set[str] = set()
        if tail_letters:
            ranked = sorted(tail_letters, key=lambda letter: counts[letter], reverse=True)
            if len(ranked) == 1 or counts[ranked[0]] > counts[ranked[1]]:
                strong.add(ranked[0])
        # Island letters stranded in the "<" filler zone: a 1-2 letter run
        # followed by a filler run ("<<"). Exception: when that "<<" is the
        # primary surname/given separator itself, the letters are a genuine
        # surname suffix ("WALKER<JR<<"), not filler -- skip only that one.
        island_separator = field.find("<<")
        for island in re.finditer(r"(?<=<)([A-Z]{1,2})(?=<<)", field):
            if island.end(1) == island_separator:
                continue
            strong.update(island.group(1))
        fillers = tail_letters | strong

        if fillers:
            # Iteratively clean the field, growing the filler set as we go:
            # - ABSORB: a new letter trapped inside a filler run ("KKKSKKK", or
            #   "KKKS" at field end) is itself a misread filler; learning it as
            #   STRONG lets its siblings bled onto the names fall too.
            # - DISSOLVE: a strong filler letter followed by "<" or another
            #   filler is a misread "<" ("SAYPADITHS<" -> "SAYPADITH<<"); the
            #   genuine first letter of a name after the separator, and weak
            #   fillers ending a real name, are never touched.
            for _ in range(6):
                all_class = "[" + re.escape("".join(sorted(fillers))) + "]"

                def absorb(match: re.Match[str]) -> str:
                    letter = match.group(1)
                    # Promote to STRONG only on unambiguous evidence: the letter
                    # is sandwiched by DIFFERENT filler characters ("KSK", or
                    # "KS" at field end). A letter run of itself in tail garbage
                    # ("KEEE") is absorbed but stays weak, so it can never clip
                    # a genuine name ending in that letter.
                    source = match.string
                    left = source[match.start(1) - 1]
                    right = source[match.end(1)] if match.end(1) < len(source) else "<"
                    if left != letter and (right == "<" or right != letter):
                        strong.add(letter)
                        fillers.add(letter)
                    return "<"

                absorbed = re.sub(f"(?<={all_class})([A-Z])(?={all_class}|<|$)", absorb, field)
                dissolved = absorbed
                if strong:
                    strong_class = "[" + re.escape("".join(sorted(strong))) + "]"
                    all_class = "[" + re.escape("".join(sorted(fillers))) + "]"
                    dissolved = re.sub(f"{strong_class}(?={all_class}|<)", "<", absorbed)
                if dissolved == field:
                    break
                field = dissolved
            field = re.sub("[" + re.escape("".join(sorted(fillers))) + "]{2,}", "<<", field)
        # A low-resolution pass can preserve both names but damage only the
        # surname/given-name separator. Recognize two tightly bounded forms:
        # ``SURNAME<K<GIVEN<<<<`` (one filler became a glyph) and
        # ``SURNAMEX<GIVEN<<<<`` (the first separator became a glyph). The long
        # filler run after GIVEN distinguishes these from normal spaces inside
        # a multipart surname.
        damaged_parts: list[str] | None = None
        embedded_glyph = re.match(r"^([A-Z]{4,20})<[A-Z]{1,2}<([A-Z]{4,20})<{4,}", field)
        if embedded_glyph:
            damaged_parts = [embedded_glyph.group(1), embedded_glyph.group(2)]
        else:
            single_separator = re.match(r"^([A-Z]{4,21})<([A-Z]{4,20})<{4,}", field)
            if single_separator:
                damaged_parts = [single_separator.group(1), single_separator.group(2)]

        parts = damaged_parts or field.split("<<", 1)
        # When OCR ate half of the "<<" separator ("SAYPADITH<<SAVATH" read as
        # "SAYPADITHS<SAVATHS"), everything lands in the surname part and the
        # given name comes out empty. The same happens when a later filler run
        # is read as letters: splitting on that later "<<" leaves only known
        # filler glyphs on the right ("THUMMANEEX<THANITR<<<<...OCKK"). A TD3
        # line always has both components, so in either case treat the first
        # single "<" as the damaged surname/given separator. A real multipart
        # surname remains safe because its right side contains a substantive
        # given-name token rather than filler-only OCR noise.
        tail_is_filler = False
        if len(parts) > 1:
            tail_letters_only = re.sub(r"[^A-Z]", "", parts[1])
            tail_is_filler = bool(tail_letters_only) and all(ch in fillers for ch in tail_letters_only)
        if fillers and (len(parts) == 1 or not parts[1].strip("<") or tail_is_filler) and "<" in parts[0].strip("<"):
            parts = parts[0].split("<", 1)
        elif len(parts) > 1 and not parts[1].strip("<"):
            damaged_separator = re.fullmatch(r"([A-Z]{4,20})<[A-Z]{1,2}<([A-Z]{4,20})", parts[0].strip("<"))
            if damaged_separator:
                parts = [damaged_separator.group(1), damaged_separator.group(2)]
        surname = MrzAnalyzer._clean_name_segment(parts[0])
        # Collapsing filler runs can leave stray "<" at the head of the given
        # segment; a genuine segment never starts with "<", so strip them or the
        # cleaner would treat the whole segment as filler and return nothing.
        given = MrzAnalyzer._clean_name_segment(parts[1].lstrip("<")) if len(parts) > 1 else ""
        if fillers:

            def _drop_pure_filler(name: str) -> str:
                return " ".join(tok for tok in name.split(" ") if tok and not all(ch in fillers for ch in tok))

            surname = _drop_pure_filler(surname)
            given = _drop_pure_filler(given)
        return surname, given

    @staticmethod
    def _realign_td3_line1(line1: str, consensus_nat: str | None = None) -> str:
        """Undo a spurious doubled leading type character.

        OCR sometimes reads the line-1 prefix "POLAO..." as "PPOLAO...", which
        shifts the 3-letter issuing country and every name character one place to
        the right (surname "CHANTHABANDITH" -> "OCHANTHABANDITH"). Because "PP"
        is also a legitimate national subtype, paired-country consensus must
        preserve it when the original country field is corroborated. Line 1
        carries no check digit, so this positional cue is the only bounded
        self-correction available for the name field."""
        if len(line1) >= 6 and line1[1] == "P":
            # PP is also a legitimate national document subtype (for example,
            # Japanese ordinary passports). Keep it when its country field is
            # corroborated by the paired data-line candidates.
            if consensus_nat and line1[2:5] == consensus_nat:
                return line1
            shifted = (line1[1:] + "<")[:44]
            if consensus_nat:
                return shifted if shifted[2:5] == consensus_nat else line1
            if shifted[1] != "P" and shifted[2:5].isalpha():
                return shifted
        return line1

    def _select_td3_pair(self, lines: list[str]) -> tuple[str, str, dict[str, Any]] | None:
        best: tuple[float, int, int, str, str, dict[str, Any]] | None = None
        # Consensus issuing country across the data-line candidates: the 3-letter
        # code at positions 10-12 (digit look-alikes mapped back to letters). A
        # line-1 whose country matches this consensus is far more trustworthy
        # than one carrying an OCR-invented country ("MRO"), which no data line
        # corroborates.
        nat_table = str.maketrans({"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "4": "A", "6": "G"})
        nat_votes: dict[str, int] = {}
        for candidate in lines:
            if len(candidate) >= 13 and sum(ch.isdigit() for ch in candidate) >= 8:
                code = candidate[10:13].translate(nat_table)
                if code.isalpha():
                    nat_votes[code] = nat_votes.get(code, 0) + 1
        consensus_nat = max(nat_votes, key=lambda key: nat_votes[key]) if nat_votes else None
        for line1_index, line1 in enumerate(lines):
            # ICAO TD3 line 1 is "P" + a type subcategory + 3-letter issuing
            # country + names. The subcategory may be "<" OR a national subtype
            # letter (e.g. Lao passports use "PO", diplomatic "PD", service
            # "PS"). Requiring "P<" wrongly rejected every two-letter-type
            # passport before its check digits were ever evaluated. The name line
            # is alphabetic, so a digit-count guard still separates it from the
            # digit-heavy data line (whose positions 1+ are the document number).
            # Malaysian TD3 passports can place the holder's complete legal
            # name in one identifier field, separated only by single filler
            # chevrons (``P<MYSWAN<DALILA<...``). There is no surname/given
            # ``<<`` boundary on those documents. Accept that country-specific
            # form only when it has a credible name-field shape; the paired
            # data line must still pass every ICAO check below.
            standard_name_field = "<<" in line1
            malaysian_single_field = (
                line1[2:5] == "MYS"
                and line1.count("<") >= 5
                and not any(char.isdigit() for char in line1[:42])
            )
            if not line1 or line1[0] != "P" or not (standard_name_field or malaysian_single_field):
                continue
            if not (line1[1] == "<" or "A" <= line1[1] <= "Z"):
                continue
            # A low-resolution name line can render terminal filler chevrons as
            # digits even though the paired data line is perfectly readable.
            # Permit a small tail-only run after the surname separator; digits
            # in the issuer/surname portion still disqualify the candidate.
            separator = line1.find("<<", 5)
            digit_positions = [index for index, char in enumerate(line1) if char.isdigit()]
            tail_digit_noise = (
                separator >= 5
                and len(digit_positions) <= 8
                and all(index > separator for index in digit_positions)
            )
            if len(digit_positions) > 5 and not tail_digit_noise:
                continue
            line1 = self._realign_td3_line1(line1, consensus_nat)
            for line2_index, line2 in enumerate(lines):
                if line1_index == line2_index:
                    continue
                parsed = self._parse_td3(line1, line2)
                observed_nationality = line2[10:13].translate(nat_table)
                # For the passport-only TD3 flow, issuing state (line 1) and
                # nationality (line 2) must corroborate. Nationality has no
                # check digit, so permitting a valid date/number tail to pair
                # with an unrelated noisy name line can produce a fully checked
                # but wrong identity. Normalize only common OCR look-alikes and
                # reject that cross-country pairing before scoring.
                if (
                    parsed.get("valid")
                    and observed_nationality.isalpha()
                    and line1[2:5].isalpha()
                    and line1[2:5] != observed_nationality
                ):
                    continue
                # OCR can accidentally combine visible-zone words into two
                # 44-character lines. If an invalid pair yields neither TD3 date,
                # it is not credible MRZ evidence; let the visible-field fallback
                # handle the document instead of producing a hard mismatch.
                if (
                    not parsed["valid"]
                    and parsed.get("date_of_birth") is None
                    and parsed.get("expiry_date") is None
                ):
                    continue
                # A two-letter document type ("PM", "PD") is only accepted from
                # OCR when the pair yields a parseable expiry date. This keeps
                # the newly-allowed types (Korean "PMKOR...") from promoting pure
                # garbage name lines into a false MRZ read, while the generic
                # "P<" path keeps its softer, evidence-based fallback behavior.
                if line1[1] != "<" and parsed.get("expiry_date") is None:
                    continue
                score = 0.0
                score += 10.0 if parsed["valid"] else 0.0
                score += 4.0 if parsed["format_valid"] else 0.0
                score += 3.0 if parsed["check_digits_valid"] else 0.0
                # A clean TD3 data line carries optional-data and composite
                # check digits in addition to the three primary checks. Prefer
                # that stronger evidence over a truncated line that happens to
                # collide on the primary digits.
                score += 5.0 if parsed.get("optional_check_digit_valid") is True else 0.0
                score += 5.0 if parsed.get("composite_check_digit_valid") is True else 0.0
                score += 2.0 if parsed.get("sex") in {"M", "F", "<"} else -2.0
                score += 1.0 if parsed.get("expiry_date") else 0.0
                score += 0.4 if line2_index > line1_index else 0.0
                score += max(0.0, 1.0 - abs((line2_index - line1_index) - 1) * 0.18)
                score += min(len(str(parsed.get("full_name") or "")) / 5.0, 5.0)
                # Prefer a clearly read surname/given-name separator. Missing
                # separators merge both names through OCR artifacts such as
                # ``...KARNSKAISAWAN...`` and can otherwise win merely because
                # the corrupted name is longer.
                name_separator = line1.find("<<", 5)
                if parsed["valid"] and 7 <= name_separator <= 24:
                    score += 10.0
                # A single filler between two substantial given-name tokens is
                # meaningful (TIMOTHY<GEORG), not tail padding. Prefer it over
                # an equally valid pass that merges the names through a noisy
                # filler glyph (TIMOTHYCGEORG).
                name_field = line1[name_separator + 2 :] if name_separator >= 0 else ""
                if re.search(r"[A-Z]{3,}<[A-Z]{3,}", name_field):
                    score += 2.0
                # Prefer cleanly-read lines: a candidate whose filler zone is
                # littered with misread letters is less trustworthy, and its
                # junk can inflate the name-length bonus (a bled "S" makes the
                # name longer, outscoring the clean read of the same passport).
                score -= 0.75 * len(self._filler_letters(line1))
                # Corroborate the line-1 country against the data-line consensus.
                if consensus_nat and line1[2:5].isalpha():
                    score += 4.0 if line1[2:5] == consensus_nat else -4.0
                parsed_nat = str(parsed.get("nationality") or "")
                if parsed_nat.isalpha() and len(parsed_nat) == 3 and line1[2:5].isalpha():
                    score += 6.0 if line1[2:5] == parsed_nat else -6.0
                # Between two otherwise-equal data lines, prefer the one whose
                # nationality field was read as clean letters (no digit
                # look-alikes) -- a proxy for the cleaner overall read, which
                # breaks ties like a document number "M..." vs "W..." that share
                # a check digit.
                if line2[10:13].isalpha():
                    score += 1.5
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
        # Nationality (line 2, pos 10-12) and the issuing country (line 1, pos
        # 2-4) are the same ICAO 3-letter state code. It is alphabetic by spec,
        # so when OCR mangles the line-2 value into non-letters (e.g. LAO -> 1OO)
        # but the line-1 issuer is a clean 3-letter code, use the issuer.
        nationality = line2[10:13].translate(
            str.maketrans({"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "4": "A", "6": "G"})
        ).replace("<", "")
        issuer = line1[2:5]
        if not nationality.isalpha() and issuer.isalpha():
            nationality = issuer

        if issuer == "MYS" and "<<" not in line1[5:]:
            # Malaysian passports may encode the complete name as a single
            # identifier. Preserve its printed order instead of forcing a
            # surname/given-name split that is absent from the MRZ.
            full_name = self._clean_name_segment(line1[5:44]) or None
        else:
            surname, given = self._extract_mrz_names(
                line1,
                nationality if nationality.isalpha() and len(nationality) == 3 else None,
            )
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
            "nationality": nationality,
            "date_of_birth": parsed_birth,
            "expiry_date": parsed_expiry,
            "sex": line2[20],
        }

    # For check-digit-guided repair: every digit an OCR letter plausibly stands
    # for, most likely first. The default digit_map takes the first entry; the
    # rest are only tried when a field's check digit rejects the first choice.
    _DIGIT_ALTERNATIVES = {
        "O": ("0",), "Q": ("0",), "D": ("0",),
        "I": ("1",), "L": ("1",),
        "Z": ("2", "7"),
        "S": ("5", "3"),
        "B": ("8", "3"),
        "G": ("6", "9"),
        "T": ("7", "1"),
        "E": ("8", "6"),
        "A": ("4",),
        # Adjacent vertical strokes merge in low-light MRZ captures. These are
        # only tried for the alphanumeric document number after its own check
        # digit rejects the original OCR text.
        "N": ("M",),
        "H": ("M", "N"),
    }

    @staticmethod
    def _normalize_td3_fields(line1: str, line2: str) -> tuple[str, str]:
        chars = list(line2)
        # TD3 document numbers are alphanumeric. Do not eagerly turn a valid
        # letter such as Q in PAQ172270 into zero; preserve the original field
        # first and only try OCR look-alikes when its own check digit fails.
        numeric_positions = {9} | set(range(13, 20)) | set(range(21, 28)) | {42, 43}
        digit_map = {
            "O": "0",
            "Q": "0",
            "D": "0",
            "I": "1",
            "L": "1",
            "Z": "2",
            "S": "5",
            "B": "8",
            "G": "6",
            "T": "7",
            "E": "8",
            "A": "4",
        }
        for index in numeric_positions:
            if index < len(chars) and chars[index] in digit_map:
                chars[index] = digit_map[chars[index]]
        # Sex (pos 20) is not check-digit protected; N/H are common misreads of M.
        if len(chars) > 20 and chars[20] in ("N", "H", "W"):
            chars[20] = "M"
        # Check-digit-guided repair: when a numeric field fails its check digit,
        # retry the positions where OCR produced a LETTER with that letter's
        # other digit look-alikes (e.g. expiry "S50604" read from "350604":
        # S->5 fails the check, S->3 passes, so 3 was the printed digit). The
        # check digit is the oracle, so this can only turn wrong reads into
        # values the document itself vouches for.
        for start, end, check_pos in ((0, 9, 9), (13, 19, 19), (21, 27, 27)):
            if len(chars) <= check_pos or not chars[check_pos].isdigit():
                continue
            field = "".join(chars[start:end])
            if MrzAnalyzer._check_digit(field) == chars[check_pos]:
                continue
            for index in range(start, end):
                original = line2[index] if index < len(line2) else "<"
                alternatives = MrzAnalyzer._DIGIT_ALTERNATIVES.get(original, ())
                if start == 0:
                    # Passport numbers are alphanumeric, so a check digit alone
                    # is not enough evidence for ambiguous second-choice
                    # substitutions such as B -> 3. Keep only the most likely
                    # glyph repair, except for the observed N/H -> M merge in
                    # low-light Japanese captures. Cross-pass corroboration can
                    # still restore a different leading letter when another OCR
                    # pass read the checked number cleanly.
                    if original == "N":
                        alternatives = ("M",)
                    elif original == "H":
                        alternatives = ("M", "N")
                    else:
                        alternatives = alternatives[:1]
                else:
                    # Date fields already received their most likely digit
                    # mapping above, so only try the remaining alternatives.
                    alternatives = alternatives[1:]
                for alternative in alternatives:
                    candidate = field[: index - start] + alternative + field[index - start + 1 :]
                    if MrzAnalyzer._check_digit(candidate) == chars[check_pos]:
                        chars[index] = alternative
                        field = candidate
                        break
                else:
                    continue
                break
        return line1, "".join(chars)

    @staticmethod
    def _clean_name_segment(segment: str) -> str:
        # A single "<" separates real name tokens. Runs of two or more "<"
        # start the MRZ filler area; OCR can hallucinate letters inside that
        # filler, so ignore anything after the filler starts.
        meaningful = re.split(r"<{2,}", segment, maxsplit=1)[0]
        # ICAO name fields contain letters and filler separators, never digits.
        # Drop digit-bearing OCR debris and any stranded one-letter tail that
        # precedes it (for example ``...CARLOS<S<98``).
        tokens = [token for token in meaningful.split("<") if token and token.isalpha()]
        while len(tokens) > 1 and len(tokens[-1]) == 1:
            tokens.pop()
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
            "MRZ_NOT_CONFIDENT",
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
        if ocr_text is None and not context.checks.get("mrz_found"):
            self._flag_if_mirrored(context, extracted_text)
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

    def _flag_if_mirrored(self, context: FraudContext, original_text: str | None) -> None:
        """When the MRZ cannot be read, check whether the image was presented
        mirrored / reversed -- typically a front (selfie) camera flipping the
        frame, so the passport text and MRZ read backwards. We horizontally flip
        the image and re-read. The document is labelled mirrored only when the
        flipped image yields a fully check-digit-valid MRZ. Filler counts and an
        invalid MRZ-like pair are diagnostics, not proof of reversal.

        Emits a specific retake signal instead of a generic "MRZ not read"."""
        try:
            flipped = context.image.transpose(Image.FLIP_LEFT_RIGHT)
        except (OSError, ValueError):
            return
        probe = FraudContext(
            content=context.content,
            filename=context.filename,
            image=flipped,
            width=flipped.width,
            height=flipped.height,
            format=context.format,
            exif_count=0,
        )
        flipped_text = self.ocr.extract(probe, document_type="passport") or ""
        self.mrz.analyze(probe, ocr_text=flipped_text)

        flip_fillers = flipped_text.count("<")
        original_fillers = (original_text or "").count("<")
        mirrored = bool(
            probe.checks.get("mrz_found")
            and probe.checks.get("mrz_check_digits_valid") is True
        )
        context.checks["document_mirror_flip_fillers"] = flip_fillers
        context.checks["document_mirror_original_fillers"] = original_fillers
        if mirrored:
            context.checks["document_mirrored"] = True
            context.signals.append(
                _signal(
                    "DOCUMENT_MIRRORED",
                    "The passport looks mirrored or reversed — its text and code read backwards. "
                    "If you used a front (selfie) camera it flipped the image; hold the photo page "
                    "facing the camera and retake.",
                    "high",
                    0.85,
                )
            )


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
