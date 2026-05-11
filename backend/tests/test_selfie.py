from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from app.models.schemas import FraudSignal
from app.services.face_biometrics import FaceEmbeddingResult, OnnxAntiSpoofModel, PassiveSpoofResult
from app.services.face_biometrics import PassiveSpoofAnalyzer
from app.services.selfie import SelfieAnalyzer


class FakeFaceRecognizer:
    def __init__(
        self,
        embedding: list[float] | None = None,
        score: float = 0.94,
        multiple_faces: bool = False,
        confidence: float = 0.99,
    ) -> None:
        self.embedding = embedding or [1.0, 0.0, 0.0]
        self.score = score
        self.multiple_faces = multiple_faces
        self.confidence = confidence

    def extract(self, content: bytes, source: str) -> FaceEmbeddingResult:
        signals = []
        if self.multiple_faces:
            signals.append(FraudSignal(code="SELFIE_MULTIPLE_FACES", label="Multiple faces detected in selfie frame.", severity="high", score=0.86))
        if self.confidence < 0.82:
            signals.append(FraudSignal(code="SELFIE_FACE_CONFIDENCE_LOW", label="Detected face is not confident enough for human selfie verification.", severity="high", score=0.86))
        return FaceEmbeddingResult(
            embedding=self.embedding,
            face_detected=True,
            face_confidence=self.confidence,
            face_box=(250, 200, 400, 450),
            checks={
                f"{source}_face_model": "fake",
                f"{source}_face_count": 2 if self.multiple_faces else 1,
                f"{source}_face_confidence": self.confidence,
            },
            signals=signals,
        )

    def compare(self, embedding_a: list[float] | None, embedding_b: list[float] | None) -> float:
        return self.score


class FakePassiveSpoofAnalyzer:
    def __init__(self, risk: float = 0.12, passed: bool = True) -> None:
        self.risk = risk
        self.passed = passed

    def analyze(self, content: bytes, face_box=None) -> PassiveSpoofResult:
        return PassiveSpoofResult(
            risk=self.risk,
            passed=self.passed,
            checks={"passive_spoof_model": "fake", "passive_spoof_risk": self.risk},
        )


class FakeOnnxAntiSpoofModel:
    def __init__(self, model_id: str, family: str, risk: float, confidence: float = 0.95) -> None:
        self.model_id = model_id
        self.family = family
        self.risk = risk
        self.confidence = confidence

    def predict(self, image: Image.Image, face_box=None):
        return {
            "status": "available",
            "family": self.family,
            "risk": self.risk,
            "real_probability": 1 - self.risk,
            "spoof_probability": self.risk,
            "confidence": self.confidence,
        }


def _jpeg_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=94)
    return buffer.getvalue()


def test_facenox_model_asset_is_identified() -> None:
    model = OnnxAntiSpoofModel(Path("best_model_quantized.onnx"))

    assert model.model_id == "facenox_best_model_quantized"
    assert model.family == "facenox_minifas_v2_se"


def test_facenox_primary_can_veto_companion_false_positive() -> None:
    analyzer = PassiveSpoofAnalyzer(model_paths=())
    analyzer._models = [
        FakeOnnxAntiSpoofModel("facenox_best_model_quantized", "facenox_minifas_v2_se", risk=0.02),
        FakeOnnxAntiSpoofModel("MiniFASNetV2", "silent_face_anti_spoofing_minifas", risk=0.99),
        FakeOnnxAntiSpoofModel("MiniFASNetV1SE", "silent_face_anti_spoofing_minifas", risk=0.96),
    ]
    image = Image.new("RGB", (640, 480), (190, 190, 190))

    result = analyzer._model_spoof_result(image, (220, 90, 190, 240))

    assert result["risk"] < 0.35
    assert result["checks"]["passive_spoof_primary_model_available"] is True


def test_non_image_selfie_is_rejected() -> None:
    analysis = SelfieAnalyzer().analyze(b"not an image", "selfie.txt", reference_embedding=[1.0, 0.0, 0.0])

    assert analysis.passive_liveness_passed is False
    assert analysis.passive_liveness_risk == 1.0
    assert analysis.face_match_score == 0.0
    assert {signal.code for signal in analysis.selfie_signals} == {"SELFIE_NOT_IMAGE"}


def test_centered_face_like_selfie_passes_lightweight_checks() -> None:
    image = Image.new("RGB", (900, 1200), (210, 214, 220))
    draw = ImageDraw.Draw(image)
    draw.ellipse((260, 210, 640, 650), fill=(198, 142, 105), outline=(70, 48, 42), width=6)
    draw.ellipse((360, 370, 390, 400), fill=(30, 30, 35))
    draw.ellipse((510, 370, 540, 400), fill=(30, 30, 35))
    draw.arc((380, 470, 520, 560), 15, 165, fill=(85, 40, 45), width=8)
    draw.rectangle((320, 650, 580, 1040), fill=(35, 52, 78))

    analyzer = SelfieAnalyzer(face_recognizer=FakeFaceRecognizer(), passive_spoof=FakePassiveSpoofAnalyzer())
    analysis = analyzer.analyze(_jpeg_bytes(image), "selfie.jpg", reference_embedding=[1.0, 0.0, 0.0])

    assert analysis.passive_liveness_passed is True
    assert analysis.face_match_score == 0.94
    assert analysis.selfie_quality_score and analysis.selfie_quality_score > 0.45
    assert analysis.passive_liveness_risk is not None and analysis.passive_liveness_risk < 0.46


def test_selfie_with_wrong_face_is_rejected() -> None:
    image = Image.new("RGB", (900, 1200), (210, 214, 220))
    draw = ImageDraw.Draw(image)
    draw.ellipse((260, 210, 640, 650), fill=(198, 142, 105), outline=(70, 48, 42), width=6)
    draw.rectangle((320, 650, 580, 1040), fill=(35, 52, 78))
    analyzer = SelfieAnalyzer(face_recognizer=FakeFaceRecognizer(score=0.41), passive_spoof=FakePassiveSpoofAnalyzer())

    analysis = analyzer.analyze(_jpeg_bytes(image), "selfie.jpg", reference_embedding=[1.0, 0.0, 0.0])

    assert analysis.passive_liveness_passed is False
    assert analysis.face_match_score == 0.41
    assert "FACE_MATCH_LOW" in {signal.code for signal in analysis.selfie_signals}


def test_sface_borderline_but_valid_match_can_pass() -> None:
    image = Image.new("RGB", (900, 1200), (210, 214, 220))
    draw = ImageDraw.Draw(image)
    draw.ellipse((260, 210, 640, 650), fill=(198, 142, 105), outline=(70, 48, 42), width=6)
    draw.rectangle((320, 650, 580, 1040), fill=(35, 52, 78))
    analyzer = SelfieAnalyzer(face_recognizer=FakeFaceRecognizer(score=0.76), passive_spoof=FakePassiveSpoofAnalyzer())

    analysis = analyzer.analyze(_jpeg_bytes(image), "selfie.jpg", reference_embedding=[1.0, 0.0, 0.0])

    assert analysis.passive_liveness_passed is True
    assert analysis.face_match_score == 0.76
    assert "FACE_MATCH_LOW" not in {signal.code for signal in analysis.selfie_signals}


def test_selfie_screen_spoof_is_rejected() -> None:
    image = Image.new("RGB", (900, 1200), (210, 214, 220))
    draw = ImageDraw.Draw(image)
    draw.ellipse((260, 210, 640, 650), fill=(198, 142, 105), outline=(70, 48, 42), width=6)
    analyzer = SelfieAnalyzer(
        face_recognizer=FakeFaceRecognizer(score=0.95),
        passive_spoof=FakePassiveSpoofAnalyzer(risk=0.78, passed=False),
    )

    analysis = analyzer.analyze(_jpeg_bytes(image), "selfie.jpg", reference_embedding=[1.0, 0.0, 0.0])

    assert analysis.passive_liveness_passed is False
    assert analysis.passive_liveness_risk == 0.78


def test_selfie_with_multiple_faces_is_rejected() -> None:
    image = Image.new("RGB", (900, 1200), (210, 214, 220))
    analyzer = SelfieAnalyzer(
        face_recognizer=FakeFaceRecognizer(score=0.95, multiple_faces=True),
        passive_spoof=FakePassiveSpoofAnalyzer(),
    )

    analysis = analyzer.analyze(_jpeg_bytes(image), "screen-replay.jpg", reference_embedding=[1.0, 0.0, 0.0])

    assert analysis.passive_liveness_passed is False
    assert "SELFIE_MULTIPLE_FACES" in {signal.code for signal in analysis.selfie_signals}


def test_low_confidence_face_detection_is_rejected() -> None:
    image = Image.new("RGB", (1200, 1200), (150, 170, 90))
    analyzer = SelfieAnalyzer(
        face_recognizer=FakeFaceRecognizer(score=0.95, confidence=0.75),
        passive_spoof=FakePassiveSpoofAnalyzer(),
    )

    analysis = analyzer.analyze(_jpeg_bytes(image), "not-human.jpg", reference_embedding=[1.0, 0.0, 0.0])

    assert analysis.passive_liveness_passed is False
    assert "SELFIE_FACE_CONFIDENCE_LOW" in {signal.code for signal in analysis.selfie_signals}


def test_passive_spoof_detects_phone_screen_frame() -> None:
    image = Image.new("RGB", (1000, 760), (215, 218, 222))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((220, 70, 780, 700), radius=28, fill=(18, 18, 22), outline=(5, 5, 8), width=16)
    draw.rectangle((255, 120, 745, 650), fill=(232, 226, 215))
    draw.ellipse((380, 205, 620, 485), fill=(198, 142, 105), outline=(70, 48, 42), width=5)
    draw.ellipse((438, 325, 460, 348), fill=(30, 30, 35))
    draw.ellipse((540, 325, 562, 348), fill=(30, 30, 35))
    draw.rectangle((380, 485, 620, 650), fill=(35, 52, 78))
    analyzer = SelfieAnalyzer(face_recognizer=FakeFaceRecognizer(score=0.95))

    analysis = analyzer.analyze(_jpeg_bytes(image), "phone-screen.jpg", reference_embedding=[1.0, 0.0, 0.0])

    assert analysis.passive_liveness_passed is False
    assert "SELFIE_PHONE_SCREEN_FRAME" in {signal.code for signal in analysis.selfie_signals}
