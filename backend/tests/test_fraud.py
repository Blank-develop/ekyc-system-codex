from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFilter

from app.core.config import get_settings
from app.services.document_models import DocumentFraudModelEnsemble, DocumentModelFinding, DocumentModelInput
from app.services.fraud import LaoIdCardFraudAnalyzer, MrzAnalyzer, PassportFraudAnalyzer

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


def _printed_passport_on_paper_image() -> bytes:
    passport = Image.open(BytesIO(_passport_like_image())).convert("RGB").resize((880, 590))
    paper = Image.new("RGB", (1300, 950), (247, 246, 240))
    draw = ImageDraw.Draw(paper)
    draw.rectangle((80, 70, 1220, 880), fill=(250, 249, 244), outline=(215, 213, 204), width=4)

    # Simulate print-copy halftone dots over the copied passport area.
    for y in range(0, passport.height, 10):
        for x in range(0, passport.width, 10):
            color = (185, 185, 180) if (x // 10 + y // 10) % 2 == 0 else (224, 224, 218)
            ImageDraw.Draw(passport).ellipse((x + 3, y + 3, x + 5, y + 5), fill=color)

    paper.paste(passport, (210, 175))
    return _jpeg_bytes(paper)


def _lao_id_like_image() -> bytes:
    image = Image.new("RGB", (1200, 760), (238, 235, 220))
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 70, 1140, 690), outline=(50, 65, 80), width=7)
    draw.rectangle((110, 180, 410, 580), outline=(80, 90, 105), width=4)
    draw.ellipse((180, 235, 340, 420), fill=(198, 142, 105), outline=(70, 48, 42), width=5)
    draw.rectangle((160, 420, 360, 580), fill=(35, 52, 78))
    for y, text in [
        (135, "LAO NATIONAL ID CARD"),
        (205, "ID NO 123456789012"),
        (265, "NAME SOMPHET TESTUSER"),
        (325, "NATIONALITY LAO"),
        (385, "DATE OF BIRTH 09/11/2001"),
        (445, "EXPIRY 14/03/2032"),
    ]:
        draw.text((480, y), text, fill=(30, 36, 42))
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


def test_printed_passport_on_paper_is_rejected() -> None:
    analysis = PassportFraudAnalyzer().analyze(_printed_passport_on_paper_image(), "printed-passport-paper.jpg", ocr_text=VALID_TD3_MRZ)

    assert analysis.status == "rejected"
    assert "DOCUMENT_PRINT_COPY_RISK_HIGH" in {signal.code for signal in analysis.signals}
    assert analysis.checks["model_heuristic_print_copy_v1_score"] >= 0.62


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


def test_borderline_portrait_substitution_score_is_not_auto_rejected() -> None:
    class BorderlinePortraitModel:
        model_id = "heuristic_portrait_substitution_v1"
        family = "tamper"

        def analyze(self, payload: DocumentModelInput) -> DocumentModelFinding:
            return DocumentModelFinding(
                model_id=self.model_id,
                family="tamper",
                score=0.5,
                confidence=0.85,
                version="test",
                reason="unit-test borderline portrait mismatch",
            )

    analyzer = PassportFraudAnalyzer(model_ensemble=DocumentFraudModelEnsemble([BorderlinePortraitModel()]))
    analysis = analyzer.analyze(_passport_like_image(), "borderline-passport.jpg", ocr_text=VALID_TD3_MRZ)

    assert analysis.status == "passed"
    assert "DOCUMENT_FACE_SUBSTITUTION_RISK_HIGH" not in {signal.code for signal in analysis.signals}
    assert "DOCUMENT_FACE_SUBSTITUTION_RISK_MEDIUM" in {signal.code for signal in analysis.signals}


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


def test_passport_with_strong_visible_fields_can_continue_when_mrz_ocr_is_weak() -> None:
    noisy_sideways_passport_ocr = "\n".join(
        [
            "RDP LAO LAO PDR",
            "Passport No PA0499974",
            "SENGVILAY",
            "KHATTHAPHONE",
            "Nationality LAO",
            "31 MAR 1998",
            "04 JUN 2035",
            "POLAOSRRO ST",
            "PDMELMGGMMATTRAPHONE<<<",
            "SPPHBPNOPROSSMSS060K2<<",
        ]
    )

    analysis = PassportFraudAnalyzer().analyze(_passport_like_image(), "sideways-real-passport.jpg", ocr_text=noisy_sideways_passport_ocr)

    assert analysis.status == "passed"
    assert "MRZ_NOT_READ" not in {signal.code for signal in analysis.signals}
    assert "MRZ_NOT_CONFIDENT" in {signal.code for signal in analysis.signals}
    assert analysis.checks["mrz_found"] is False
    assert analysis.checks["passport_text_evidence_score"] >= 0.65


def test_lao_id_card_like_image_can_pass_without_mrz() -> None:
    ocr_text = "\n".join(
        [
            "LAO NATIONAL ID CARD",
            "ID NO 123456789012",
            "NAME SOMPHET TESTUSER",
            "NATIONALITY LAO",
            "DATE OF BIRTH 09/11/2001",
            "EXPIRY 14/03/2032",
        ]
    )

    analysis = LaoIdCardFraudAnalyzer().analyze(_lao_id_like_image(), "lao-id.jpg", ocr_text=ocr_text)

    assert analysis.status == "passed"
    assert analysis.ocr.document_type == "lao_id_card"
    assert analysis.ocr.id_number == "123456789012"
    assert analysis.ocr.nationality == "LAO"
    assert analysis.ocr.mrz_valid is None
    assert "MRZ_NOT_READ" not in {signal.code for signal in analysis.signals}


def test_lao_id_card_rejects_when_id_number_is_missing() -> None:
    analysis = LaoIdCardFraudAnalyzer().analyze(_lao_id_like_image(), "lao-id.jpg", ocr_text="LAO NATIONAL ID CARD NAME SOMPHET")

    assert analysis.status == "rejected"
    assert "LAO_ID_NUMBER_NOT_READ" in {signal.code for signal in analysis.signals}


def test_lao_id_card_uses_latest_future_date_as_expiry() -> None:
    ocr_text = "\n".join(
        [
            "LAO NATIONAL ID CARD",
            "NO 100187899",
            "01 / 09 / 2001",
            "24 / O5 / 2023",
            "24 / O5 / 202B",
        ]
    )

    analysis = LaoIdCardFraudAnalyzer().analyze(_lao_id_like_image(), "lao-id.jpg", ocr_text=ocr_text)

    assert analysis.ocr.expiry_date is not None
    assert str(analysis.ocr.expiry_date) == "2028-05-24"
    assert "LAO_ID_EXPIRED" not in {signal.code for signal in analysis.signals}


def test_lao_id_card_extracts_name_from_split_english_labels() -> None:
    ocr_text = "\n".join(
        [
            "LAO PEOPLE DEMOCRATIC REPUBLIC",
            "ID NO 100187899",
            "Nom / Surname",
            "SOUKSAVANH",
            "Prenoms / Given names",
            "PELAY",
            "Date of birth 09/11/2001",
            "Date of expiry 24/05/2028",
        ]
    )

    analysis = LaoIdCardFraudAnalyzer().analyze(_lao_id_like_image(), "lao-id.jpg", ocr_text=ocr_text)

    assert analysis.ocr.full_name == "SOUKSAVANH PELAY"
    assert str(analysis.ocr.expiry_date) == "2028-05-24"
    assert analysis.ocr.extracted_fields["full_name"] == "SOUKSAVANH PELAY"
    assert analysis.ocr.extracted_fields["expiry_date"] == "2028-05-24"


def test_lao_id_card_extracts_lao_script_name_when_ocr_provides_it() -> None:
    ocr_text = "\n".join(
        [
            "ເລກທີ 10-0187899",
            "ຊື່ແລະນາມສະກຸນ ສົມໄຊ ສີສຸວັນ",
            "ວັນເກີດ 01/09/2001",
            "ບັດໝົດອາຍຸ 24/05/2028",
        ]
    )

    analysis = LaoIdCardFraudAnalyzer().analyze(_lao_id_like_image(), "lao-id.jpg", ocr_text=ocr_text)

    assert analysis.ocr.full_name == "ສົມໄຊ ສີສຸວັນ"
    assert str(analysis.ocr.expiry_date) == "2028-05-24"


def test_lao_id_card_prefers_surya_ocr_when_enabled(monkeypatch) -> None:
    class FakeSuryaOcrExtractor:
        def __init__(self, enabled: bool) -> None:
            self.enabled = enabled

        def extract(self, context) -> str:
            context.checks["surya_ocr_available"] = self.enabled
            return "\n".join(
                [
                    "Nom / Surname",
                    "SOUKSAVANH",
                    "Prenoms / Given names",
                    "PELAY",
                    "NO 100187899",
                    "24/05/2028",
                ]
            )

    monkeypatch.setenv("LALIGENCE_LAO_ID_OCR_ENGINE", "surya")
    get_settings.cache_clear()
    monkeypatch.setattr("app.services.fraud.SuryaOcrExtractor", FakeSuryaOcrExtractor)

    try:
        analysis = LaoIdCardFraudAnalyzer().analyze(_lao_id_like_image(), "lao-id.jpg")

        assert analysis.checks["ocr_engine"] == "surya"
        assert analysis.ocr.full_name == "SOUKSAVANH PELAY"
        assert str(analysis.ocr.expiry_date) == "2028-05-24"
    finally:
        get_settings.cache_clear()


def test_lao_id_card_does_not_treat_issue_date_as_expiry() -> None:
    ocr_text = "\n".join(
        [
            "NO 100187899",
            "01/09/2001",
            "24/05/2023",
        ]
    )

    analysis = LaoIdCardFraudAnalyzer().analyze(_lao_id_like_image(), "lao-id.jpg", ocr_text=ocr_text)
    codes = {signal.code for signal in analysis.signals}

    assert analysis.ocr.expiry_date is None
    assert "LAO_ID_EXPIRED" not in codes
    assert "LAO_ID_TEXT_WEAK" not in codes


def test_lao_id_card_rejects_confident_expired_expiry_date() -> None:
    ocr_text = "\n".join(
        [
            "LAO NATIONAL ID CARD",
            "NO 100187899",
            "DATE OF BIRTH 01/09/2001",
            "EXPIRY 24/05/2023",
        ]
    )

    analysis = LaoIdCardFraudAnalyzer().analyze(_lao_id_like_image(), "lao-id.jpg", ocr_text=ocr_text)

    assert str(analysis.ocr.expiry_date) == "2023-05-24"
    assert "LAO_ID_EXPIRED" in {signal.code for signal in analysis.signals}


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


def test_mrz_parser_stitches_split_lao_passport_name_line() -> None:
    noisy_ocr = "\n".join(
        [
            "POLAOSENGVILAY<<KHATTH",
            "APHONE<<<<<<<<<<<<<<<<",
            "2404999747009803318M3506042<<<",
        ]
    )

    result = MrzAnalyzer().analyze(_context_stub(), ocr_text=noisy_ocr)

    assert result.mrz_valid is True
    assert result.passport_number == "PA0499974"
    assert result.full_name == "KHATTHAPHONE SENGVILAY"
    assert str(result.expiry_date) == "2035-06-04"


def test_mrz_parser_recovers_compressed_lao_passport_digit_line() -> None:
    noisy_ocr = "\n".join(
        [
            "P<LAOSENGVILAY<<KHATTHAPHONE<X<<<<<<<<<<<<<<",
            "494999747LA09803318NS506042<<<<",
        ]
    )

    result = MrzAnalyzer().analyze(_context_stub(), ocr_text=noisy_ocr)

    assert result.mrz_valid is True
    assert result.passport_number == "PA0499974"
    assert result.full_name == "KHATTHAPHONE SENGVILAY"
    assert str(result.expiry_date) == "2035-06-04"


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


def test_mrz_name_parser_drops_trailing_single_character_filler_token() -> None:
    mrz = "\n".join(
        [
            "P<LAOSENGVILAY<<KHATTHAPHONE<X<<<<<<<<<<<<<<",
            "PA04999747LAO9803318M3506042<<<<<<<<<<<<<<<2",
        ]
    )

    result = MrzAnalyzer().analyze(_context_stub(), ocr_text=mrz)

    assert result.mrz_valid is True
    assert result.full_name == "KHATTHAPHONE SENGVILAY"


def _context_stub():
    image = Image.new("RGB", (100, 100), "white")
    loaded = PassportFraudAnalyzer().loader.load(_jpeg_bytes(image), "stub.jpg")
    assert not hasattr(loaded, "status")
    return loaded


def test_mrz_name_extraction_survives_filler_letters_and_doubled_type() -> None:
    # OCR renders MRZ "<" filler as repeated letters (K/S) and sometimes doubles
    # the leading type character; names must still come out clean.
    cases = [
        ("POLAOSAYPADITH<<SAVATH" + "<" * 22, "SAYPADITH", "SAVATH"),
        ("POLAOSAYPADITH<<SAVATH" + "K" * 22, "SAYPADITH", "SAVATH"),
        ("POLAOSAYPADITHS<SAVATHS" + "KKKKKSKKKKKKSKKKKKKS"[:21], "SAYPADITH", "SAVATH"),
        ("PPOLAOSOUKSOMBATH<<VILAYPHONK<<<KKKKEKKKKKK", "SOUKSOMBATH", "VILAYPHON"),
        # tail read correctly as "<" but fillers touching the names became "S"
        ("POLAOSAYPADITHS<SAVATHS" + "<<S<<<<<<<<<S<<<<<<<<"[:21], "SAYPADITH", "SAVATH"),
        ("POLAOSAYPADITHS<<SAVATHS" + "<S<<<<<<<<<<<<<<<<<<"[:20], "SAYPADITH", "SAVATH"),
        # genuine multi-part given names must never be clipped
        ("P<IDNWAHYU<<DENI<SETIA" + "<" * 22, "WAHYU", "DENI SETIA"),
    ]
    for line1, expected_surname, expected_given in cases:
        realigned = MrzAnalyzer._realign_td3_line1((line1 + "<" * 44)[:44])
        surname, given = MrzAnalyzer._extract_mrz_names(realigned)
        assert surname == expected_surname, line1
        assert given == expected_given, line1


def test_mrz_check_digit_guided_repair_of_misread_digit() -> None:
    # Expiry "350604" OCR-read as "S50604": the default S->5 mapping fails the
    # check digit, S->3 passes, so the parser must adopt 3 (and stay valid)
    # instead of reporting a check-digit mismatch on a genuine passport.
    mrz = "\n".join(
        [
            "POLAOSENGVILAY<<KHATTHAPHONE<<<<<<<<<<<<<<<<",
            "PA04999747LAO9BO331BNS5O6O42<<<<<<<<<<<<<<<2",
        ]
    )
    result = MrzAnalyzer().analyze(_context_stub(), ocr_text=mrz)

    assert result.mrz_valid is True
    assert result.mrz_check_digits_valid is True
    assert str(result.expiry_date) == "2035-06-04"
    assert str(result.date_of_birth) == "1998-03-31"
    assert result.extracted_fields.get("sex") == "M"
