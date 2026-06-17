from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol

from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat

from app.models.schemas import FraudSignal


ModelFamily = Literal["document_liveness", "tamper", "general_fraud"]
ModelStatus = Literal["available", "unavailable", "error"]


def _clamp(value: float) -> float:
    return max(0.0, min(value, 1.0))


def _signal(code: str, label: str, severity: str, score: float) -> FraudSignal:
    return FraudSignal(code=code, label=label, severity=severity, score=round(_clamp(score), 2))


@dataclass(frozen=True)
class DocumentModelInput:
    image: Image.Image
    checks: Mapping[str, float | int | str | bool | None]


@dataclass(frozen=True)
class DocumentModelFinding:
    model_id: str
    family: ModelFamily
    score: float
    confidence: float
    status: ModelStatus = "available"
    version: str = "unknown"
    reason: str = ""


@dataclass(frozen=True)
class DocumentModelEnsembleResult:
    recapture_risk: float = 0.0
    tamper_risk: float = 0.0
    document_fraud_risk: float = 0.0
    confidence: float = 0.0
    findings: list[DocumentModelFinding] = field(default_factory=list)
    signals: list[FraudSignal] = field(default_factory=list)
    checks: dict[str, float | int | str | bool | None] = field(default_factory=dict)


class DocumentFraudModel(Protocol):
    model_id: str
    family: ModelFamily

    def analyze(self, payload: DocumentModelInput) -> DocumentModelFinding:
        ...


class HeuristicDocumentLivenessModel:
    """Baseline document liveness model.

    This is intentionally lightweight: it behaves like a model adapter and
    emits the same finding shape that a trained recapture detector will emit.
    """

    model_id = "heuristic_document_liveness_v1"
    family: ModelFamily = "document_liveness"

    def analyze(self, payload: DocumentModelInput) -> DocumentModelFinding:
        checks = payload.checks
        glare = float(checks.get("glare_ratio", 0) or 0)
        blockiness = float(checks.get("jpeg_blockiness", 0) or 0)
        saturation = float(checks.get("saturation_extreme_ratio", 0) or 0)
        contrast = float(checks.get("contrast", 0) or 0)
        likeness = float(checks.get("document_likeness", 0) or 0)
        moire = self._screen_pattern_score(payload.image)

        contrast_risk = _clamp((26 - contrast) / 26)
        structure_risk = _clamp((0.55 - likeness) / 0.55)
        score = _clamp(
            blockiness * 0.34
            + moire * 0.28
            + glare * 1.1 * 0.18
            + saturation * 0.9 * 0.1
            + contrast_risk * 0.06
            + structure_risk * 0.04
        )
        confidence = _clamp(0.58 + min(payload.image.width * payload.image.height / 3_000_000, 0.32))
        return DocumentModelFinding(
            model_id=self.model_id,
            family=self.family,
            score=score,
            confidence=confidence,
            version="baseline-heuristic-1",
            reason="recapture cues from compression, glare, screen pattern, and weak contrast",
        )

    @staticmethod
    def _screen_pattern_score(image: Image.Image) -> float:
        gray = ImageOps.grayscale(image).resize((384, max(1, round(384 / (image.width / max(image.height, 1))))))
        edges = gray.filter(ImageFilter.FIND_EDGES)
        edge_mean = ImageStat.Stat(edges).mean[0] / 255
        sharpened = gray.filter(ImageFilter.SHARPEN)
        high_freq = ImageStat.Stat(ImageOps.autocontrast(sharpened.filter(ImageFilter.FIND_EDGES))).stddev[0] / 128
        return _clamp(edge_mean * 0.55 + high_freq * 0.45)


class HeuristicPrintCopyModel:
    """Printed document copy detector.

    Looks for a passport/ID image placed inside a larger paper sheet, plus
    print-like texture cues. This targets common presentation attacks where a
    copied passport is printed on office paper and re-photographed.
    """

    model_id = "heuristic_print_copy_v1"
    family: ModelFamily = "document_liveness"

    def analyze(self, payload: DocumentModelInput) -> DocumentModelFinding:
        nested_sheet = self._nested_sheet_score(payload.image)
        halftone = self._halftone_texture_score(payload.image)
        flat_paper = self._flat_paper_score(payload.image)
        score = _clamp(nested_sheet * 0.72 + halftone * 0.18 + flat_paper * 0.1)
        confidence = _clamp(0.58 + min(payload.image.width * payload.image.height / 3_000_000, 0.28))
        reason = (
            "printed-copy cues "
            f"(nested_sheet={nested_sheet:.2f}, halftone={halftone:.2f}, flat_paper={flat_paper:.2f})"
        )
        return DocumentModelFinding(
            model_id=self.model_id,
            family=self.family,
            score=score,
            confidence=confidence,
            version="paper-print-heuristic-1",
            reason=reason,
        )

    @staticmethod
    def _nested_sheet_score(image: Image.Image) -> float:
        try:
            import cv2
            import numpy as np
        except ImportError:
            return 0.0

        width, height = image.size
        scale = 760 / max(width, height)
        resized = image.resize((max(1, int(width * scale)), max(1, int(height * scale))))
        rgb = np.asarray(resized)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 36, 118)
        contours, _ = cv2.findContours(edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

        center_x = resized.width / 2
        center_y = resized.height / 2
        image_area = resized.width * resized.height
        center_rects: list[tuple[float, float]] = []
        for contour in contours:
            perimeter = cv2.arcLength(contour, True)
            if perimeter <= 0:
                continue
            approx = cv2.approxPolyDP(contour, 0.025 * perimeter, True)
            if len(approx) != 4 or not cv2.isContourConvex(approx):
                continue
            area = abs(cv2.contourArea(approx))
            area_ratio = area / max(image_area, 1)
            if area_ratio < 0.12 or area_ratio > 0.94:
                continue
            x, y, w, h = cv2.boundingRect(approx)
            if not (x <= center_x <= x + w and y <= center_y <= y + h):
                continue
            rectangularity = area / max(w * h, 1)
            aspect = w / max(h, 1)
            if rectangularity < 0.58 or not (0.55 <= aspect <= 2.2):
                continue
            center_rects.append((area_ratio, rectangularity))

        if len(center_rects) < 2:
            if not center_rects:
                return 0.0
            main_area, main_rectangularity = max(center_rects)
            # A genuine camera capture usually fills most of the frame with
            # the document. A printed copy often appears as a smaller document
            # rectangle sitting inside a larger paper sheet.
            return _clamp((0.62 - main_area) / 0.36 * main_rectangularity)
        center_rects.sort(reverse=True)
        outer_area, outer_rectangularity = center_rects[0]
        inner_area, inner_rectangularity = center_rects[1]
        separation = outer_area - inner_area
        if separation < 0.12:
            return _clamp((0.62 - outer_area) / 0.36 * outer_rectangularity)
        return _clamp(0.55 + separation * 0.75 + min(outer_rectangularity, inner_rectangularity) * 0.18)

    @staticmethod
    def _halftone_texture_score(image: Image.Image) -> float:
        gray = ImageOps.grayscale(image).resize((512, max(1, round(512 / (image.width / max(image.height, 1))))))
        blurred = gray.filter(ImageFilter.GaussianBlur(1.0))
        residual = ImageChops.difference(gray, blurred)
        residual_stat = ImageStat.Stat(residual)
        edge_mean = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).mean[0] / 255
        return _clamp((residual_stat.stddev[0] / 22) * 0.72 + edge_mean * 0.28)

    @staticmethod
    def _flat_paper_score(image: Image.Image) -> float:
        hsv = image.convert("HSV").resize((320, max(1, round(320 / (image.width / max(image.height, 1))))))
        pixels = list(hsv.getdata())
        if not pixels:
            return 0.0
        bright_low_sat = sum(1 for _, sat, val in pixels if sat < 32 and val > 218) / len(pixels)
        gray = ImageOps.grayscale(image)
        contrast = ImageStat.Stat(gray).stddev[0]
        return _clamp(bright_low_sat * 0.72 + ((42 - contrast) / 42) * 0.28)


class HeuristicTamperModel:
    """Baseline tamper finding adapter for edited-region risk."""

    model_id = "heuristic_tamper_v1"
    family: ModelFamily = "tamper"

    def analyze(self, payload: DocumentModelInput) -> DocumentModelFinding:
        checks = payload.checks
        ela = float(checks.get("ela_score", 0) or 0)
        blockiness = float(checks.get("jpeg_blockiness", 0) or 0)
        saturation = float(checks.get("saturation_extreme_ratio", 0) or 0)
        likeness = float(checks.get("document_likeness", 0) or 0)
        quality = float(checks.get("quality_score", 0) or 0)

        low_evidence_penalty = _clamp((0.55 - min(likeness, quality)) / 0.55)
        score = _clamp(ela * 0.55 + blockiness * 0.24 + saturation * 0.11 + low_evidence_penalty * 0.1)
        confidence = _clamp(0.52 + min(payload.image.width * payload.image.height / 3_400_000, 0.35))
        return DocumentModelFinding(
            model_id=self.model_id,
            family=self.family,
            score=score,
            confidence=confidence,
            version="baseline-heuristic-1",
            reason="tamper cues from ELA, compression inconsistency, saturation extremes, and weak evidence",
        )


class HeuristicPortraitSubstitutionModel:
    """Passport portrait-area substitution detector.

    This targets a common fraud pattern where the passport body/MRZ remains
    readable, but a cleaner digital portrait is pasted over the printed photo.
    It uses region-level inconsistency instead of full-image ELA because the
    global document can still look authentic.
    """

    model_id = "heuristic_portrait_substitution_v1"
    family: ModelFamily = "tamper"

    def analyze(self, payload: DocumentModelInput) -> DocumentModelFinding:
        if payload.checks.get("document_type") != "passport":
            return DocumentModelFinding(
                model_id=self.model_id,
                family=self.family,
                score=0.0,
                confidence=0.0,
                version="passport-layout-heuristic-1",
                reason="passport portrait substitution heuristic skipped for non-passport document",
            )

        photo = self._region_stats(self._crop(payload.image, (0.055, 0.22, 0.32, 0.735)))
        body = self._region_stats(self._crop(payload.image, (0.35, 0.2, 0.94, 0.7)))

        contrast_ratio = photo["contrast"] / max(body["contrast"], 1.0)
        noise_ratio = photo["noise"] / max(body["noise"], 0.1)
        saturation_gap = abs(photo["saturation"] - body["saturation"])
        dark_gap = photo["dark_ratio"] - body["dark_ratio"]
        mrz_valid = bool(payload.checks.get("mrz_valid"))

        portrait_presence = _clamp((photo["skin_ratio"] - 0.16) / 0.26)
        contrast_mismatch = _clamp((contrast_ratio - 1.55) / 1.2)
        noise_mismatch = _clamp(abs(noise_ratio - 1.0) / 0.85)
        saturation_mismatch = _clamp(saturation_gap / 75)
        dark_mismatch = _clamp((dark_gap - 0.04) / 0.14)
        printed_texture_mismatch = 1.0 if photo["contrast"] > 42 and body["contrast"] < 38 else 0.0

        score = _clamp(
            portrait_presence
            * (
                contrast_mismatch * 0.4
                + noise_mismatch * 0.2
                + saturation_mismatch * 0.14
                + dark_mismatch * 0.14
                + printed_texture_mismatch * 0.12
            )
        )
        if mrz_valid and saturation_gap < 22 and 0.45 <= noise_ratio <= 0.9:
            score = min(score, 0.32)
        confidence = _clamp(0.62 + min(payload.image.width * payload.image.height / 3_200_000, 0.28))
        reason = (
            "portrait region differs from passport body "
            f"(contrast_ratio={contrast_ratio:.2f}, noise_ratio={noise_ratio:.2f}, "
            f"saturation_gap={saturation_gap:.1f}, skin_ratio={photo['skin_ratio']:.2f}, "
            f"mrz_valid={mrz_valid})"
        )
        return DocumentModelFinding(
            model_id=self.model_id,
            family=self.family,
            score=score,
            confidence=confidence,
            version="passport-layout-heuristic-1",
            reason=reason,
        )

    @staticmethod
    def _crop(image: Image.Image, box: tuple[float, float, float, float]) -> Image.Image:
        width, height = image.size
        left, top, right, bottom = box
        return image.crop((int(width * left), int(height * top), int(width * right), int(height * bottom)))

    @staticmethod
    def _region_stats(image: Image.Image) -> dict[str, float]:
        gray = ImageOps.grayscale(image)
        gray_stat = ImageStat.Stat(gray)
        blurred = gray.filter(ImageFilter.GaussianBlur(1.2))
        residual = ImageChops.difference(gray, blurred)
        noise = ImageStat.Stat(residual).mean[0]

        hsv = image.convert("HSV")
        hsv_pixels = list(hsv.getdata())
        rgb_pixels = list(image.getdata())
        total = max(len(rgb_pixels), 1)
        saturation = sum(sat for _, sat, _ in hsv_pixels) / total
        skin_like = 0
        dark = 0
        for red, green, blue in rgb_pixels:
            if red > 95 and green > 45 and blue > 30 and red > green and green >= blue - 8 and max(red, green, blue) - min(red, green, blue) > 15:
                skin_like += 1
            if red < 70 and green < 70 and blue < 70:
                dark += 1
        return {
            "contrast": gray_stat.stddev[0],
            "noise": noise,
            "saturation": saturation,
            "skin_ratio": skin_like / total,
            "dark_ratio": dark / total,
        }


class OptionalOnnxDocumentFraudModel:
    """Optional trained model adapter.

    Configure with LALIGENCE_DOCUMENT_FRAUD_ONNX_PATH. The expected output is
    either a single fraud probability or a vector where the fraud class index
    is read after softmax normalization.
    """

    model_id = "onnx_document_fraud"
    family: ModelFamily = "general_fraud"

    def __init__(self, model_path: str | None = None, input_name: str | None = None) -> None:
        self.model_path = model_path or os.getenv("LALIGENCE_DOCUMENT_FRAUD_ONNX_PATH")
        self.input_name = input_name or os.getenv("LALIGENCE_DOCUMENT_FRAUD_ONNX_INPUT")
        self.fraud_index = int(os.getenv("LALIGENCE_DOCUMENT_FRAUD_ONNX_FRAUD_INDEX", "-1"))
        self._session: Any | None = None
        self._load_error: str | None = None

    def analyze(self, payload: DocumentModelInput) -> DocumentModelFinding:
        if not self.model_path:
            return self._unavailable("LALIGENCE_DOCUMENT_FRAUD_ONNX_PATH is not configured")

        path = Path(self.model_path)
        if not path.exists():
            return self._unavailable(f"ONNX model file does not exist: {path}")

        session = self._get_session()
        if session is None:
            return DocumentModelFinding(
                model_id=self.model_id,
                family=self.family,
                score=0.0,
                confidence=0.0,
                status="error",
                version=path.name,
                reason=self._load_error or "ONNX runtime failed to initialize",
            )

        try:
            input_name = self.input_name or session.get_inputs()[0].name
            output = session.run(None, {input_name: self._preprocess(payload.image)})[0]
            score = self._probability(output, self.fraud_index)
        except Exception as exc:  # pragma: no cover - depends on external model runtime
            return DocumentModelFinding(
                model_id=self.model_id,
                family=self.family,
                score=0.0,
                confidence=0.0,
                status="error",
                version=path.name,
                reason=f"ONNX inference failed: {exc}",
            )

        return DocumentModelFinding(
            model_id=self.model_id,
            family=self.family,
            score=score,
            confidence=0.82,
            version=path.name,
            reason="trained ONNX document fraud model probability",
        )

    def _get_session(self) -> Any | None:
        if self._session is not None:
            return self._session
        try:
            import onnxruntime as ort
        except ImportError:
            self._load_error = "onnxruntime is not installed"
            return None

        try:
            self._session = ort.InferenceSession(str(self.model_path), providers=["CPUExecutionProvider"])
        except Exception as exc:  # pragma: no cover - depends on external model runtime
            self._load_error = f"could not load ONNX model: {exc}"
            return None
        return self._session

    @staticmethod
    def _preprocess(image: Image.Image) -> Any:
        import numpy as np

        prepared = ImageOps.exif_transpose(image).convert("RGB").resize((224, 224))
        array = np.asarray(prepared).astype("float32") / 255.0
        array = (array - 0.5) / 0.5
        return array.transpose(2, 0, 1)[None, ...]

    @staticmethod
    def _probability(output: Any, fraud_index: int) -> float:
        import numpy as np

        values = np.asarray(output, dtype="float32").reshape(-1)
        if values.size == 0:
            return 0.0
        if values.size == 1:
            value = float(values[0])
            return _clamp(1 / (1 + math.exp(-value)) if value < 0 or value > 1 else value)
        shifted = values - float(values.max())
        exp = np.exp(shifted)
        probs = exp / max(float(exp.sum()), 1e-6)
        index = fraud_index if fraud_index >= 0 else values.size + fraud_index
        index = max(0, min(int(index), values.size - 1))
        return _clamp(float(probs[index]))

    def _unavailable(self, reason: str) -> DocumentModelFinding:
        return DocumentModelFinding(
            model_id=self.model_id,
            family=self.family,
            score=0.0,
            confidence=0.0,
            status="unavailable",
            version="not-configured",
            reason=reason,
        )


class DocumentFraudModelEnsemble:
    def __init__(self, models: list[DocumentFraudModel] | None = None) -> None:
        self.models = models or [
            HeuristicDocumentLivenessModel(),
            HeuristicPrintCopyModel(),
            HeuristicTamperModel(),
            HeuristicPortraitSubstitutionModel(),
            OptionalOnnxDocumentFraudModel(),
        ]

    def analyze(self, payload: DocumentModelInput) -> DocumentModelEnsembleResult:
        findings = [model.analyze(payload) for model in self.models]
        available = [finding for finding in findings if finding.status == "available"]
        recapture = self._family_score(available, "document_liveness")
        tamper = self._family_score(available, "tamper")
        general = self._family_score(available, "general_fraud")
        fraud = _clamp(max(general, recapture * 0.45 + tamper * 0.55))
        confidence = self._confidence(available)
        signals = self._signals(recapture, tamper, fraud, confidence, available)
        checks = self._checks(findings, recapture, tamper, fraud, confidence)

        return DocumentModelEnsembleResult(
            recapture_risk=recapture,
            tamper_risk=tamper,
            document_fraud_risk=fraud,
            confidence=confidence,
            findings=findings,
            signals=signals,
            checks=checks,
        )

    @staticmethod
    def _family_score(findings: list[DocumentModelFinding], family: ModelFamily) -> float:
        family_findings = [finding for finding in findings if finding.family == family]
        if not family_findings:
            return 0.0
        weight_sum = sum(max(finding.confidence, 0.05) for finding in family_findings)
        weighted = sum(finding.score * max(finding.confidence, 0.05) for finding in family_findings) / weight_sum
        return _clamp(max(weighted, max(finding.score for finding in family_findings) * 0.9))

    @staticmethod
    def _confidence(findings: list[DocumentModelFinding]) -> float:
        if not findings:
            return 0.0
        return _clamp(sum(finding.confidence for finding in findings) / len(findings))

    @staticmethod
    def _signals(
        recapture: float,
        tamper: float,
        fraud: float,
        confidence: float,
        findings: list[DocumentModelFinding],
    ) -> list[FraudSignal]:
        signals: list[FraudSignal] = []
        portrait_score = max(
            (finding.score for finding in findings if finding.model_id == "heuristic_portrait_substitution_v1"),
            default=0.0,
        )
        print_copy_score = max(
            (finding.score for finding in findings if finding.model_id == "heuristic_print_copy_v1"),
            default=0.0,
        )
        if print_copy_score >= 0.62:
            signals.append(_signal("DOCUMENT_PRINT_COPY_RISK_HIGH", "Document appears to be a printed copy on paper.", "high", print_copy_score))
        elif print_copy_score >= 0.42:
            signals.append(_signal("DOCUMENT_PRINT_COPY_RISK_MEDIUM", "Document may be a printed paper copy.", "medium", print_copy_score))

        if portrait_score >= 0.55:
            signals.append(_signal("DOCUMENT_FACE_SUBSTITUTION_RISK_HIGH", "Passport portrait area is inconsistent with the rest of the document.", "high", portrait_score))
        elif portrait_score >= 0.38:
            signals.append(_signal("DOCUMENT_FACE_SUBSTITUTION_RISK_MEDIUM", "Passport portrait area may have been substituted or edited.", "medium", portrait_score))

        if recapture >= 0.76 and confidence >= 0.55:
            signals.append(_signal("DOCUMENT_RECAPTURE_MODEL_RISK_HIGH", "Model ensemble indicates high screen, print, or photocopy recapture risk.", "high", recapture))
        elif recapture >= 0.58:
            signals.append(_signal("DOCUMENT_RECAPTURE_MODEL_RISK_MEDIUM", "Model ensemble indicates possible recapture risk.", "medium", recapture))

        if tamper >= 0.74 and confidence >= 0.55:
            signals.append(_signal("DOCUMENT_TAMPER_MODEL_RISK_HIGH", "Model ensemble indicates high edited-document or pasted-region risk.", "high", tamper))
        elif tamper >= 0.56:
            signals.append(_signal("DOCUMENT_TAMPER_MODEL_RISK_MEDIUM", "Model ensemble indicates possible edited-document risk.", "medium", tamper))

        if fraud >= 0.78 and confidence >= 0.62:
            signals.append(_signal("DOCUMENT_FRAUD_MODEL_RISK_HIGH", "Model ensemble indicates high overall document fraud risk.", "high", fraud))
        elif fraud >= 0.6:
            signals.append(_signal("DOCUMENT_FRAUD_MODEL_RISK_MEDIUM", "Model ensemble indicates elevated overall document fraud risk.", "medium", fraud))
        return signals

    @staticmethod
    def _checks(
        findings: list[DocumentModelFinding],
        recapture: float,
        tamper: float,
        fraud: float,
        confidence: float,
    ) -> dict[str, float | int | str | bool | None]:
        checks: dict[str, float | int | str | bool | None] = {
            "document_model_architecture": "ensemble",
            "document_model_count": len(findings),
            "document_model_available_count": sum(finding.status == "available" for finding in findings),
            "document_model_recapture_risk": round(recapture, 3),
            "document_model_tamper_risk": round(tamper, 3),
            "document_model_fraud_risk": round(fraud, 3),
            "document_model_confidence": round(confidence, 3),
        }
        for finding in findings:
            prefix = f"model_{finding.model_id}"
            checks[f"{prefix}_status"] = finding.status
            checks[f"{prefix}_family"] = finding.family
            checks[f"{prefix}_score"] = round(finding.score, 3)
            checks[f"{prefix}_confidence"] = round(finding.confidence, 3)
            checks[f"{prefix}_version"] = finding.version
            checks[f"{prefix}_reason"] = finding.reason[:180]
        return checks
