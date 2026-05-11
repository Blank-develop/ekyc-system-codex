from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError

from app.models.schemas import FraudSignal, SelfieAnalysisRequest
from app.services.face_biometrics import OpenCvFaceRecognizer, PassiveSpoofAnalyzer

FACE_MATCH_PASS_THRESHOLD = 0.68
FACE_MATCH_BORDERLINE_THRESHOLD = 0.74


def _clamp(value: float) -> float:
    return max(0.0, min(value, 1.0))


def _signal(code: str, label: str, severity: str, score: float) -> FraudSignal:
    return FraudSignal(code=code, label=label, severity=severity, score=round(_clamp(score), 2))


class SelfieAnalyzer:
    """Selfie quality, passive liveness, and face verification."""

    def __init__(
        self,
        face_recognizer: OpenCvFaceRecognizer | None = None,
        passive_spoof: PassiveSpoofAnalyzer | None = None,
    ) -> None:
        self.face_recognizer = face_recognizer or OpenCvFaceRecognizer()
        self.passive_spoof = passive_spoof or PassiveSpoofAnalyzer()

    def analyze(self, content: bytes, filename: str, reference_embedding: list[float] | None = None) -> SelfieAnalysisRequest:
        signals: list[FraudSignal] = []
        try:
            raw = Image.open(BytesIO(content))
            image = ImageOps.exif_transpose(raw).convert("RGB")
        except UnidentifiedImageError:
            return SelfieAnalysisRequest(
                passive_liveness_passed=False,
                face_match_score=0.0,
                passive_liveness_risk=1.0,
                selfie_quality_score=0.0,
                selfie_checks={"filename": filename},
                selfie_signals=[_signal("SELFIE_NOT_IMAGE", "Selfie upload is not a readable image.", "high", 1.0)],
            )

        width, height = image.size
        pixels = width * height
        gray = ImageOps.grayscale(image)
        stat = ImageStat.Stat(gray)
        brightness = stat.mean[0]
        contrast = stat.stddev[0]
        sharpness = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).mean[0]
        center_skin_ratio = self._center_skin_ratio(image)
        glare_ratio = self._glare_ratio(image)

        quality = 0.24
        quality += 0.2 if pixels >= 450_000 else 0.08 if pixels >= 220_000 else 0.0
        quality += 0.18 if 55 <= brightness <= 220 else 0.04
        quality += 0.18 if contrast >= 24 else 0.07 if contrast >= 16 else 0.0
        quality += 0.16 if sharpness >= 7 else 0.08 if sharpness >= 3.2 else 0.0
        quality += 0.14 if center_skin_ratio >= 0.08 else 0.0
        quality += 0.1 if glare_ratio <= 0.12 else 0.0
        quality = _clamp(quality)

        if pixels < 220_000:
            signals.append(_signal("SELFIE_LOW_RESOLUTION", "Selfie resolution is too low.", "high", 0.76))
        if brightness < 45 or brightness > 235:
            signals.append(_signal("SELFIE_POOR_LIGHTING", "Selfie lighting is too dark or overexposed.", "medium", 0.5))
        if contrast < 16:
            signals.append(_signal("SELFIE_LOW_CONTRAST", "Selfie contrast is too low for reliable analysis.", "medium", 0.42))
        if sharpness < 1.4:
            signals.append(_signal("SELFIE_BLUR_DETECTED", "Selfie is too blurry for reliable analysis.", "high", 0.78))
        elif sharpness < 3.2:
            signals.append(_signal("SELFIE_LOW_SHARPNESS", "Selfie sharpness is low; face-match confidence may be reduced.", "medium", 0.28))
        if center_skin_ratio < 0.04:
            signals.append(_signal("FACE_NOT_CENTERED", "A face-like region was not detected near the center.", "high", 0.72))
        elif center_skin_ratio < 0.08:
            signals.append(_signal("FACE_CENTER_WEAK", "Face appears weak or off-center.", "medium", 0.36))
        if glare_ratio > 0.18:
            signals.append(_signal("SELFIE_GLARE_OR_SCREEN_RISK", "Strong glare may indicate a screen replay or poor capture.", "medium", 0.48))

        face_result = self.face_recognizer.extract(content, "selfie")
        signals.extend(face_result.signals)

        passive_result = self.passive_spoof.analyze(content, face_result.face_box)
        signals.extend(passive_result.signals)

        face_match_score = 0.0
        if reference_embedding is None:
            signals.append(_signal("PASSPORT_FACE_REFERENCE_MISSING", "Passport face embedding is missing; selfie cannot be matched.", "high", 0.92))
        elif face_result.embedding is not None:
            face_match_score = self.face_recognizer.compare(reference_embedding, face_result.embedding)
            if face_match_score < FACE_MATCH_PASS_THRESHOLD:
                signals.append(_signal("FACE_MATCH_LOW", "Selfie face does not match the passport portrait.", "high", 1 - face_match_score))
            elif face_match_score < FACE_MATCH_BORDERLINE_THRESHOLD:
                signals.append(_signal("FACE_MATCH_BORDERLINE", "Selfie face match is borderline.", "medium", 1 - face_match_score))

        quality_passive_risk = _clamp(
            (1 - quality) * 0.55
            + glare_ratio * 0.35
            + (0.18 if center_skin_ratio < 0.08 else 0)
            + sum(signal.score * (0.28 if signal.severity == "medium" else 0.48) for signal in signals)
        )
        passive_risk = max(quality_passive_risk, passive_result.risk)
        hard_fail = any(signal.severity == "high" for signal in signals)
        passed = (
            not hard_fail
            and passive_result.passed
            and passive_risk <= 0.5
            and quality >= 0.46
            and face_match_score >= FACE_MATCH_PASS_THRESHOLD
        )

        return SelfieAnalysisRequest(
            passive_liveness_passed=passed,
            face_match_score=round(face_match_score, 2),
            passive_liveness_risk=round(passive_risk, 2),
            selfie_quality_score=round(quality, 2),
            selfie_checks={
                "filename": filename,
                "width": width,
                "height": height,
                "megapixels": round(pixels / 1_000_000, 2),
                "brightness": round(brightness, 2),
                "contrast": round(contrast, 2),
                "sharpness": round(sharpness, 2),
                "center_skin_ratio": round(center_skin_ratio, 4),
                "glare_ratio": round(glare_ratio, 4),
                "face_match_model": "opencv_yunet_sface",
                "face_match_threshold": FACE_MATCH_PASS_THRESHOLD,
                "face_match_borderline_threshold": FACE_MATCH_BORDERLINE_THRESHOLD,
                "face_match_score_raw": round(face_match_score, 4),
                "passport_face_reference_available": reference_embedding is not None,
                **face_result.checks,
                **passive_result.checks,
            },
            selfie_signals=signals,
        )

    @staticmethod
    def _center_skin_ratio(image: Image.Image) -> float:
        width, height = image.size
        crop = image.crop((int(width * 0.28), int(height * 0.18), int(width * 0.72), int(height * 0.72))).resize((180, 220))
        total = crop.width * crop.height
        skin = 0
        for red, green, blue in crop.getdata():
            if red > 60 and green > 35 and blue > 25 and red > blue and red >= green * 0.82 and max(red, green, blue) - min(red, green, blue) > 12:
                skin += 1
        return skin / max(total, 1)

    @staticmethod
    def _glare_ratio(image: Image.Image) -> float:
        hsv = image.convert("HSV").resize((240, max(1, round(240 / (image.width / max(image.height, 1))))))
        total = hsv.width * hsv.height
        glare = 0
        for _, sat, val in hsv.getdata():
            if val >= 245 and sat <= 32:
                glare += 1
        return glare / max(total, 1)
