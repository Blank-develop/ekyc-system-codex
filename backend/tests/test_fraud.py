from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFilter

from app.services.document_models import DocumentFraudModelEnsemble, DocumentModelFinding, DocumentModelInput
from app.services.fraud import MrzAnalyzer, PassportFraudAnalyzer

VALID_TD3_MRZ = "\n".join(
    [
        "P<LAONITVONGKHAY<<CHILANHOUTH<<<<<<<<<<<<<<<",
        "PA05236O56LAOO111O9OM36O2128<<<<<<<KK<<<<<<<",
    ]
)

ICAO_SAMPLE_EXPIRED_TD3_MRZ = "\n".join(
    [
        "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<",
        "L898902C36UTO7408122F1204159ZE184226B<<<<<10",
    ]
)


def _jpeg_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=94)
    return buffer.getvalue()


def _passport_like_image() -> bytes:
    image = Image.new("RGB", (1200, 800), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 80, 1120, 720), outline="black", width=8)
    draw.rectangle((820, 180, 1040, 440), outline="black", width=4)
    for y in range(170, 600, 44):
        draw.text((150, y), "PASSPORT SAMPLE FIELD DATA 123456789", fill="black")
    return _jpeg_bytes(image)


def _portrait_substitution_image() -> bytes:
    image = Image.new("RGB", (1200, 800), (210, 196, 150))
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 35, 1170, 765), outline=(70, 65, 55), width=4)
    for y in range(120, 600, 42):
        draw.text((420, y), "PASSPORT FIELD DATA LAO 123456789", fill=(42, 39, 34))
    for x in range(0, 1200, 28):
        draw.line((x, 40, x + 260, 760), fill=(190, 176, 136), width=1)

    draw.rectangle((58, 158, 406, 602), fill=(238, 206, 184), outline=(155, 150, 132), width=3)
    draw.rectangle((58, 158, 140, 602), fill=(24, 24, 28))
    draw.rectangle((324, 158, 406, 602), fill=(24, 24, 28))
    draw.ellipse((130, 190, 335, 430), fill=(236, 190, 170))
    draw.ellipse((180, 285, 198, 302), fill=(36, 32, 30))
    draw.ellipse((267, 285, 285, 302), fill=(36, 32, 30))
    draw.arc((200, 325, 270, 365), start=15, end=165, fill=(130, 65, 65), width=4)
    draw.rectangle((112, 410, 352, 602), fill=(35, 40, 62))
    return _jpeg_bytes(image)


def test_non_image_upload_is_rejected() -> None:
    analysis = PassportFraudAnalyzer().analyze(b"not an image", "file.txt")

    assert analysis.status == "rejected"
    assert analysis.fraud_risk_score == 1.0
    assert {signal.code for signal in analysis.signals} == {"NON_IMAGE_UPLOAD"}


def test_passport_like_image_produces_explainable_scores() -> None:
    analysis = PassportFraudAnalyzer().analyze(_passport_like_image(), "passport.jpg", ocr_text=VALID_TD3_MRZ)

    assert analysis.status == "passed"
    assert analysis.image_quality_score > 0.5
    assert analysis.document_likeness_score > 0.45
    assert "brightness" in analysis.checks
    assert "ela_score" in analysis.checks
    assert analysis.checks["document_model_architecture"] == "ensemble"
    assert analysis.checks["document_model_available_count"] >= 2


def test_injected_document_model_can_drive_auto_rejection() -> None:
    class HighRiskModel:
        model_id = "test_high_risk_model"
        family = "general_fraud"

        def analyze(self, payload: DocumentModelInput) -> DocumentModelFinding:
            return DocumentModelFinding(
                model_id=self.model_id,
                family="general_fraud",
                score=0.96,
                confidence=0.91,
                version="test",
                reason="unit-test high risk finding",
            )

    analyzer = PassportFraudAnalyzer(model_ensemble=DocumentFraudModelEnsemble([HighRiskModel()]))
    analysis = analyzer.analyze(_passport_like_image(), "passport.jpg", ocr_text=VALID_TD3_MRZ)

    assert analysis.status == "rejected"
    assert "DOCUMENT_FRAUD_MODEL_RISK_HIGH" in {signal.code for signal in analysis.signals}
    assert analysis.checks["model_test_high_risk_model_score"] == 0.96


def test_portrait_substitution_region_is_rejected() -> None:
    analysis = PassportFraudAnalyzer().analyze(_portrait_substitution_image(), "face-sub.jpg")

    assert analysis.status == "rejected"
    assert "DOCUMENT_FACE_SUBSTITUTION_RISK_HIGH" in {signal.code for signal in analysis.signals}
    assert analysis.checks["model_heuristic_portrait_substitution_v1_score"] >= 0.48


def test_soft_but_structured_passport_image_is_not_hard_blur_rejected() -> None:
    image = Image.open(BytesIO(_passport_like_image())).filter(ImageFilter.GaussianBlur(radius=0.7))
    analysis = PassportFraudAnalyzer().analyze(_jpeg_bytes(image), "soft-passport.jpg", ocr_text=VALID_TD3_MRZ)

    assert analysis.status == "passed"
    assert "BLUR_DETECTED" not in {signal.code for signal in analysis.signals}
    assert analysis.fraud_risk_score < 0.5


def test_non_passport_photo_without_mrz_is_rejected() -> None:
    image = Image.new("RGB", (1200, 900), (84, 150, 58))
    draw = ImageDraw.Draw(image)
    draw.ellipse((250, 120, 560, 420), fill=(214, 126, 42), outline=(100, 62, 28), width=8)
    draw.polygon([(275, 130), (330, 20), (365, 145)], fill=(224, 150, 58), outline=(100, 62, 28))
    draw.polygon([(460, 145), (535, 35), (530, 170)], fill=(224, 150, 58), outline=(100, 62, 28))
    draw.ellipse((335, 250, 372, 288), fill=(42, 64, 45))
    draw.ellipse((445, 252, 482, 290), fill=(42, 64, 45))
    draw.rectangle((300, 420, 900, 820), fill=(198, 104, 28))
    draw.line((380, 310, 250, 260), fill=(245, 220, 170), width=3)
    draw.line((480, 315, 650, 270), fill=(245, 220, 170), width=3)

    analysis = PassportFraudAnalyzer().analyze(_jpeg_bytes(image), "cat.jpg")

    assert analysis.status == "rejected"
    assert "MRZ_NOT_READ" in {signal.code for signal in analysis.signals}


def test_mrz_check_digit_validation_for_td3() -> None:
    # ICAO-style sample MRZ with valid TD3 check digits.
    result = MrzAnalyzer().analyze(_context_stub(), ocr_text=ICAO_SAMPLE_EXPIRED_TD3_MRZ)

    assert result.mrz_valid is True
    assert result.mrz_check_digits_valid is True
    assert result.passport_number == "L898902C3"
    assert result.nationality == "UTO"


def test_mrz_parser_corrects_common_ocr_confusions() -> None:
    mrz = "\n".join(
        [
            "P<LAONITVONGKHAY<<CHILANHOUTH<<<<<<<<<<<<<<<",
            "PA05236O56LAOO111O9OM36O2128<<<<<<<KK<<<<<<<",
        ]
    )
    result = MrzAnalyzer().analyze(_context_stub(), ocr_text=mrz)

    assert result.mrz_valid is True
    assert result.mrz_check_digits_valid is True
    assert result.passport_number == "PA0523605"
    assert result.nationality == "LAO"
    assert str(result.date_of_birth) == "2001-11-09"
    assert str(result.expiry_date) == "2036-02-12"


def test_mrz_parser_recovers_short_lao_passport_ocr_lines() -> None:
    noisy_ocr = "\n".join(
        [
            "AONITVONGKHAY<<CHILANHOUTH<",
            "PA03772433LA00111090M3203145<",
        ]
    )

    result = MrzAnalyzer().analyze(_context_stub(), ocr_text=noisy_ocr)

    assert result.mrz_valid is True
    assert result.passport_number == "PA0377243"
    assert result.full_name == "CHILANHOUTH NITVONGKHAY"
    assert result.nationality == "LAO"
    assert str(result.date_of_birth) == "2001-11-09"
    assert str(result.expiry_date) == "2032-03-14"


def test_mrz_name_parser_ignores_ocr_garbage_in_filler() -> None:
    mrz = "\n".join(
        [
            "P<LAOSAYPADITH<<SAVATH<<<<<<<<<SS<KKKKKKKKKK",
            "PAQ1783585LAO94O8296M27O816O<<<<<<<<<<<<2<<<",
        ]
    )
    result = MrzAnalyzer().analyze(_context_stub(), ocr_text=mrz)

    assert result.mrz_valid is True
    assert result.full_name == "SAVATH SAYPADITH"
    assert result.passport_number == "PA0178358"
    assert str(result.date_of_birth) == "1994-08-29"
    assert str(result.expiry_date) == "2027-08-16"


def _context_stub():
    image = Image.new("RGB", (100, 100), "white")
    loaded = PassportFraudAnalyzer().loader.load(_jpeg_bytes(image), "stub.jpg")
    assert not hasattr(loaded, "status")
    return loaded
