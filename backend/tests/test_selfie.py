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


class SequencePassiveSpoofAnalyzer:
    def __init__(self, results: list[PassiveSpoofResult]) -> None:
        self.results = results
        self.index = 0

    def analyze(self, content: bytes, face_box=None) -> PassiveSpoofResult:
        result = self.results[min(self.index, len(self.results) - 1)]
        self.index += 1
        return result


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


def test_multiframe_selfie_rejects_static_replay() -> None:
    image = Image.new("RGB", (900, 1200), (210, 214, 220))
    draw = ImageDraw.Draw(image)
    draw.ellipse((260, 210, 640, 650), fill=(198, 142, 105), outline=(70, 48, 42), width=6)
    draw.ellipse((360, 370, 390, 400), fill=(30, 30, 35))
    draw.ellipse((510, 370, 540, 400), fill=(30, 30, 35))
    draw.rectangle((320, 650, 580, 1040), fill=(35, 52, 78))
    frames = [_jpeg_bytes(image) for _ in range(8)]
    analyzer = SelfieAnalyzer(face_recognizer=FakeFaceRecognizer(), passive_spoof=FakePassiveSpoofAnalyzer())

    analysis = analyzer.analyze_frames(frames, [f"frame-{index}.jpg" for index in range(len(frames))], reference_embedding=[1.0, 0.0, 0.0])

    assert analysis.passive_liveness_passed is False
    assert "SELFIE_BURST_STATIC_REPLAY" in {signal.code for signal in analysis.selfie_signals}


def test_multiframe_selfie_rejects_recurring_strong_display_surface() -> None:
    image = Image.new("RGB", (900, 1200), (210, 214, 220))
    draw = ImageDraw.Draw(image)
    draw.ellipse((260, 210, 640, 650), fill=(198, 142, 105), outline=(70, 48, 42), width=6)
    draw.rectangle((320, 650, 580, 1040), fill=(35, 52, 78))
    frames = [_jpeg_bytes(image) for _ in range(8)]
    sequence = SequencePassiveSpoofAnalyzer([
        PassiveSpoofResult(
            risk=0.48,
            passed=True,
            checks={
                "passive_spoof_risk": 0.58,
                "passive_spoof_display_surface_score": 0.64,
                "passive_spoof_screen_frame_score": 0.32,
                "passive_spoof_model_risk": 0.12,
                "passive_spoof_glare_ratio": 0.24,
            },
            signals=[],
        )
        for _ in frames
    ])
    analyzer = SelfieAnalyzer(face_recognizer=FakeFaceRecognizer(), passive_spoof=sequence)

    analysis = analyzer.analyze_frames(frames, [f"frame-{index}.jpg" for index in range(len(frames))], reference_embedding=[1.0, 0.0, 0.0])

    assert analysis.passive_liveness_passed is False
    assert "SELFIE_BURST_DISPLAY_REPLAY" in {signal.code for signal in analysis.selfie_signals}


def test_multiframe_selfie_allows_medium_display_background_cues() -> None:
    frames = []
    for index in range(8):
        image = Image.new("RGB", (900, 1200), (210 + index % 3, 214 + index % 2, 220))
        draw = ImageDraw.Draw(image)
        offset = index % 4
        draw.rectangle((86, 120, 205, 720), fill=(44, 50, 58))
        draw.rectangle((680, 80, 780, 720), fill=(196, 202, 208))
        draw.ellipse((260 + offset, 210, 640 + offset, 650), fill=(198, 142, 105), outline=(70, 48, 42), width=6)
        draw.ellipse((360 + offset, 370, 390 + offset, 400), fill=(30, 30, 35))
        draw.ellipse((510 + offset, 370, 540 + offset, 400), fill=(30, 30, 35))
        draw.rectangle((320 + offset, 650, 580 + offset, 1040), fill=(35, 52, 78))
        frames.append(_jpeg_bytes(image))
    sequence = SequencePassiveSpoofAnalyzer([
        PassiveSpoofResult(
            risk=0.48,
            passed=True,
            checks={
                "passive_spoof_risk": 0.48,
                "passive_spoof_display_surface_score": 0.46,
                "passive_spoof_screen_frame_score": 0.08,
                "passive_spoof_held_phone_score": 0.06,
                "passive_spoof_model_risk": 0.18,
                "passive_spoof_glare_ratio": 0.12,
            },
            signals=[
                FraudSignal(
                    code="SELFIE_POSSIBLE_DISPLAY_SURFACE",
                    label="Possible tablet or display surface cues appear around the face.",
                    severity="medium",
                    score=0.46,
                )
            ],
        )
        for _ in frames
    ])
    analyzer = SelfieAnalyzer(face_recognizer=FakeFaceRecognizer(), passive_spoof=sequence)

    analysis = analyzer.analyze_frames(frames, [f"frame-{index}.jpg" for index in range(len(frames))], reference_embedding=[1.0, 0.0, 0.0])

    assert analysis.passive_liveness_passed is True
    assert "SELFIE_BURST_DISPLAY_REPLAY" not in {signal.code for signal in analysis.selfie_signals}


def test_multiframe_selfie_allows_generic_high_risk_without_hard_replay_cues() -> None:
    frames = []
    for index in range(8):
        image = Image.new("RGB", (900, 1200), (210 + index % 3, 214 + index % 2, 220))
        draw = ImageDraw.Draw(image)
        offset = index % 4
        draw.rectangle((86, 120, 205, 720), fill=(44, 50, 58))
        draw.ellipse((260 + offset, 210, 640 + offset, 650), fill=(198, 142, 105), outline=(70, 48, 42), width=6)
        draw.ellipse((360 + offset, 370, 390 + offset, 400), fill=(30, 30, 35))
        draw.ellipse((510 + offset, 370, 540 + offset, 400), fill=(30, 30, 35))
        draw.rectangle((320 + offset, 650, 580 + offset, 1040), fill=(35, 52, 78))
        frames.append(_jpeg_bytes(image))
    sequence = SequencePassiveSpoofAnalyzer([
        PassiveSpoofResult(
            risk=0.82,
            passed=True,
            checks={
                "passive_spoof_risk": 0.82,
                "passive_spoof_display_surface_score": 0.48,
                "passive_spoof_screen_frame_score": 0.08,
                "passive_spoof_held_phone_score": 0.04,
                "passive_spoof_paper_photo_score": 0.04,
                "passive_spoof_model_risk": 0.18,
                "passive_spoof_heuristic_risk": 0.82,
            },
            signals=[
                FraudSignal(
                    code="PASSIVE_SPOOF_RISK_HIGH",
                    label="Passive liveness indicates likely screen/photo replay.",
                    severity="high",
                    score=0.82,
                ),
                FraudSignal(
                    code="SELFIE_POSSIBLE_DISPLAY_SURFACE",
                    label="Possible tablet or display surface cues appear around the face.",
                    severity="medium",
                    score=0.48,
                ),
            ],
        )
        for _ in frames
    ])
    analyzer = SelfieAnalyzer(face_recognizer=FakeFaceRecognizer(), passive_spoof=sequence)

    analysis = analyzer.analyze_frames(frames, [f"frame-{index}.jpg" for index in range(len(frames))], reference_embedding=[1.0, 0.0, 0.0])

    assert analysis.passive_liveness_passed is True
    assert "PASSIVE_SPOOF_RISK_HIGH" not in {signal.code for signal in analysis.selfie_signals}


def test_multiframe_selfie_rejects_recurring_held_phone_screen() -> None:
    image = Image.new("RGB", (900, 1200), (210, 214, 220))
    draw = ImageDraw.Draw(image)
    draw.ellipse((260, 210, 640, 650), fill=(198, 142, 105), outline=(70, 48, 42), width=6)
    draw.rectangle((320, 650, 580, 1040), fill=(35, 52, 78))
    frames = [_jpeg_bytes(image) for _ in range(8)]
    sequence = SequencePassiveSpoofAnalyzer([
        PassiveSpoofResult(
            risk=0.36,
            passed=True,
            checks={
                "passive_spoof_risk": 0.36,
                "passive_spoof_display_surface_score": 0.22,
                "passive_spoof_screen_frame_score": 0.18,
                "passive_spoof_held_phone_score": 0.44,
                # A genuine held-phone replay keeps the PAD model risk elevated;
                # this corroboration is what confirms the held-phone hard-fail.
                "passive_spoof_model_risk": 0.6,
            },
            signals=[],
        )
        for _ in frames
    ])
    analyzer = SelfieAnalyzer(face_recognizer=FakeFaceRecognizer(), passive_spoof=sequence)

    analysis = analyzer.analyze_frames(frames, [f"frame-{index}.jpg" for index in range(len(frames))], reference_embedding=[1.0, 0.0, 0.0])

    assert analysis.passive_liveness_passed is False
    assert "SELFIE_BURST_HELD_PHONE_REPLAY" in {signal.code for signal in analysis.selfie_signals}


def test_multiframe_selfie_allows_held_phone_false_positive_with_low_model() -> None:
    # A real face (e.g. glasses/reflections) can trip the held-phone heuristic while
    # the PAD model stays LOW. Without model corroboration this must NOT hard-fail —
    # the fix for genuine faces being wrongly rejected as a replay.
    image = Image.new("RGB", (900, 1200), (210, 214, 220))
    draw = ImageDraw.Draw(image)
    draw.ellipse((260, 210, 640, 650), fill=(198, 142, 105), outline=(70, 48, 42), width=6)
    draw.rectangle((320, 650, 580, 1040), fill=(35, 52, 78))
    frames = [_jpeg_bytes(image) for _ in range(8)]
    sequence = SequencePassiveSpoofAnalyzer([
        PassiveSpoofResult(
            risk=0.36,
            passed=True,
            checks={
                "passive_spoof_risk": 0.36,
                "passive_spoof_display_surface_score": 0.22,
                "passive_spoof_screen_frame_score": 0.18,
                "passive_spoof_held_phone_score": 0.44,   # recurring heuristic hit
                "passive_spoof_model_risk": 0.12,          # but model says genuine
            },
            signals=[],
        )
        for _ in frames
    ])
    analyzer = SelfieAnalyzer(face_recognizer=FakeFaceRecognizer(), passive_spoof=sequence)

    analysis = analyzer.analyze_frames(frames, [f"frame-{index}.jpg" for index in range(len(frames))], reference_embedding=[1.0, 0.0, 0.0])

    assert "SELFIE_BURST_HELD_PHONE_REPLAY" not in {signal.code for signal in analysis.selfie_signals}


def test_multiframe_selfie_live_like_motion_can_pass() -> None:
    frames = []
    for index in range(8):
        image = Image.new("RGB", (900, 1200), (210 + index % 3, 214 + index % 2, 220))
        draw = ImageDraw.Draw(image)
        offset = index % 4
        draw.ellipse((260 + offset, 210, 640 + offset, 650), fill=(198, 142, 105), outline=(70, 48, 42), width=6)
        draw.ellipse((360 + offset, 370, 390 + offset, 400), fill=(30, 30, 35))
        draw.ellipse((510 + offset, 370, 540 + offset, 400), fill=(30, 30, 35))
        draw.rectangle((320 + offset, 650, 580 + offset, 1040), fill=(35, 52, 78))
        frames.append(_jpeg_bytes(image))
    analyzer = SelfieAnalyzer(face_recognizer=FakeFaceRecognizer(), passive_spoof=FakePassiveSpoofAnalyzer())

    analysis = analyzer.analyze_frames(frames, [f"frame-{index}.jpg" for index in range(len(frames))], reference_embedding=[1.0, 0.0, 0.0])

    assert analysis.passive_liveness_passed is True
    assert "SELFIE_BURST_STATIC_REPLAY" not in {signal.code for signal in analysis.selfie_signals}


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


def test_passive_spoof_detects_held_phone_screen_with_visible_fingers() -> None:
    image = Image.new("RGB", (1000, 760), (198, 204, 208))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((250, 45, 760, 735), radius=36, fill=(16, 18, 24), outline=(4, 5, 8), width=18)
    draw.rectangle((292, 85, 718, 700), fill=(228, 232, 226))
    draw.rounded_rectangle((200, 250, 285, 455), radius=35, fill=(196, 138, 103))
    draw.rounded_rectangle((720, 260, 805, 485), radius=35, fill=(198, 140, 105))
    draw.ellipse((380, 185, 640, 500), fill=(198, 142, 105), outline=(70, 48, 42), width=5)
    draw.ellipse((455, 330, 478, 353), fill=(30, 30, 35))
    draw.ellipse((545, 330, 568, 353), fill=(30, 30, 35))
    draw.arc((470, 398, 570, 470), 15, 165, fill=(85, 40, 45), width=6)
    draw.rectangle((412, 500, 608, 700), fill=(40, 58, 88))
    analyzer = SelfieAnalyzer(
        face_recognizer=FakeFaceRecognizer(score=0.95),
        passive_spoof=PassiveSpoofAnalyzer(model_paths=()),
    )

    analysis = analyzer.analyze(_jpeg_bytes(image), "held-phone-screen.jpg", reference_embedding=[1.0, 0.0, 0.0])

    assert analysis.passive_liveness_passed is False
    codes = {signal.code for signal in analysis.selfie_signals}
    # The phone-screen frame is the dominant cue for this synthetic attack and
    # hard-fails it. The held-phone bezel score is deliberately two-sided now,
    # so it no longer false-rejects live selfies with a dark object on one side.
    assert "SELFIE_PHONE_SCREEN_FRAME" in codes


def test_held_phone_score_low_for_one_sided_dark_object() -> None:
    # A genuine selfie with a dark object (e.g. a jacket) on ONE side and a
    # plain bright wall on the other must not read as a held phone.
    image = Image.new("RGB", (1000, 760), (205, 208, 210))
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 120, 360, 700), fill=(18, 20, 24))  # dark object, left side only
    face_box = (430, 200, 240, 300)

    score = PassiveSpoofAnalyzer._held_phone_score(image, face_box)

    assert score < 0.36, f"one-sided dark object scored as held phone: {score}"


def test_passive_spoof_detects_tablet_screen_surface_when_frame_is_clipped() -> None:
    image = Image.new("RGB", (1000, 760), (176, 182, 190))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((-30, -20, 1030, 790), radius=36, fill=(20, 22, 28), outline=(8, 9, 12), width=18)
    draw.rectangle((38, 36, 962, 724), fill=(238, 238, 232))
    draw.ellipse((330, 180, 670, 570), fill=(198, 142, 105), outline=(86, 60, 48), width=3)
    draw.ellipse((420, 335, 445, 360), fill=(25, 25, 28))
    draw.ellipse((555, 335, 580, 360), fill=(25, 25, 28))
    draw.arc((430, 410, 575, 500), 20, 160, fill=(95, 45, 50), width=5)
    draw.rectangle((385, 570, 615, 730), fill=(80, 72, 120))
    draw.polygon([(705, 20), (795, 20), (520, 740), (430, 740)], fill=(248, 248, 248))
    analyzer = SelfieAnalyzer(
        face_recognizer=FakeFaceRecognizer(score=0.95),
        passive_spoof=PassiveSpoofAnalyzer(model_paths=()),
    )

    analysis = analyzer.analyze(_jpeg_bytes(image), "tablet-screen-replay.jpg", reference_embedding=[1.0, 0.0, 0.0])

    assert analysis.passive_liveness_passed is False
    assert "SELFIE_TABLET_SCREEN_SURFACE" in {signal.code for signal in analysis.selfie_signals}


def test_bare_shoulders_large_face_does_not_trigger_paper_photo() -> None:
    # A real bare-shouldered selfie against a bright wall: skin on both sides,
    # bright low-saturation surround, but a large face. The grip-skin paper
    # heuristic must not read this as a held printed sheet.
    width, height = 1280, 720
    image = Image.new("RGB", (width, height), (236, 232, 220))  # bright cream wall
    draw = ImageDraw.Draw(image)
    # bare shoulders: skin across the lower frame
    draw.rectangle((0, 560, width, height), fill=(198, 150, 120))
    # large centered face (width ~0.27 of frame, above the 0.22 small-face gate)
    face_w = int(width * 0.27)
    fx = width // 2 - face_w // 2
    fy = 180
    face_h = int(face_w * 1.3)
    draw.ellipse((fx, fy, fx + face_w, fy + face_h), fill=(201, 150, 116))

    score = PassiveSpoofAnalyzer._paper_photo_score(image, (fx, fy, face_w, face_h))
    assert score < 0.56


def test_passive_spoof_detects_printed_photo_paper() -> None:
    image = Image.new("RGB", (1000, 760), (198, 206, 202))
    draw = ImageDraw.Draw(image)
    draw.polygon([(170, 42), (805, 82), (760, 704), (128, 660)], fill=(242, 240, 234), outline=(132, 134, 130))
    draw.rectangle((285, 138, 690, 590), fill=(229, 225, 214), outline=(178, 178, 170), width=5)
    draw.ellipse((340, 170, 635, 510), fill=(198, 142, 105), outline=(82, 58, 50), width=5)
    draw.ellipse((420, 310, 445, 335), fill=(30, 30, 35))
    draw.ellipse((530, 310, 555, 335), fill=(30, 30, 35))
    draw.arc((430, 380, 550, 460), 15, 165, fill=(85, 40, 45), width=6)
    draw.rectangle((385, 510, 590, 590), fill=(80, 72, 110))
    analyzer = SelfieAnalyzer(
        face_recognizer=FakeFaceRecognizer(score=0.95),
        passive_spoof=PassiveSpoofAnalyzer(model_paths=()),
    )

    analysis = analyzer.analyze(_jpeg_bytes(image), "printed-photo-paper.jpg", reference_embedding=[1.0, 0.0, 0.0])

    assert analysis.passive_liveness_passed is False
    assert "SELFIE_PRINTED_PHOTO_PAPER" in {signal.code for signal in analysis.selfie_signals}
