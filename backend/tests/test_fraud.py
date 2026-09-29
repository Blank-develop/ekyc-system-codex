from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFilter

from app.core.config import get_settings
from app.services.document_models import DocumentFraudModelEnsemble, DocumentModelFinding, DocumentModelInput
from app.services.fraud import LaoIdCardFraudAnalyzer, MrzAnalyzer, OcrTextExtractor, PassportFraudAnalyzer

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


def test_portrait_passport_ocr_includes_full_page_rotation_candidates() -> None:
    portrait_capture = Image.new("RGB", (800, 956), "white")

    region_names = {
        name
        for name, _ in OcrTextExtractor._ocr_regions(
            portrait_capture,
            include_passport_rotations=True,
        )
    }

    assert "full_rot90" in region_names
    assert "full_rot270" in region_names


def test_portrait_passport_ocr_includes_framed_sideways_mrz_candidates() -> None:
    portrait_capture = Image.new("RGB", (690, 840), "white")

    regions = {
        name: (region.size, psm)
        for name, region, psm in OcrTextExtractor._passport_mrz_regions(portrait_capture)
    }

    assert "mrz_rot90_rotated_framed" in regions
    assert "mrz_rot270_rotated_framed" in regions
    assert "mrz_rot90_bottom_safe_tight_soft" in regions
    assert "mrz_rot270_bottom_safe_tight_soft" in regions
    assert regions["mrz_rot90_rotated_framed"][1] == 6
    assert regions["mrz_rot90_bottom_safe_tight_soft"][1] == 11
    assert regions["mrz_rot90_rotated_framed"][0][0] > regions["mrz_rot90_rotated_framed"][0][1]


def test_printed_name_repairs_single_character_mrz_ocr_substitution() -> None:
    corrected = MrzAnalyzer._corroborate_name_with_printed_fields(
        "JOSTE MENDOZA ALVITE",
        "ALVITE\nJOSIE MENDOZA\nUNITED STATES OF AMERICA",
    )

    assert corrected == "JOSIE MENDOZA ALVITE"


def test_printed_name_pair_prefers_complete_identity_tokens_over_ocr_noise() -> None:
    corrected = MrzAnalyzer._corroborate_name_with_printed_fields(
        "UENNS MONECHANDY",
        "\n".join(
            [
                "GS",
                "UENNS",
                "MONECHANDY",
                "OVER",
                "MONECHANDY",
                "NATTHANIT",
                "P<LAOMONECHANDY<<NATTHANIT<<<<<<<<<<<<<<<<",
            ]
        ),
    )

    assert corrected == "NATTHANIT MONECHANDY"


def test_printed_name_pair_replaces_over_noise_without_replacing_surname() -> None:
    corrected = MrzAnalyzer._corroborate_name_with_printed_fields(
        "OVER MONECHANDY",
        "\n".join(
            [
                "MONECHANDY",
                "NATTHANIT",
                "OVER",
                "P<LAOMONECHANDY<<NATTHANIT<<<<<<<<<<<<<<<<<<",
            ]
        ),
    )

    assert corrected == "NATTHANIT MONECHANDY"


def test_printed_name_pair_does_not_degrade_repeated_correct_name() -> None:
    corrected = MrzAnalyzer._corroborate_name_with_printed_fields(
        "NATTHANIT MONECHANDY",
        "\n".join(
            [
                "NNS",
                "MONECHANDY",
                "NATTHANIT",
                "SHNOLNL",
                "MONECHANDY",
                "NATTHANIT",
                "P<LAOMONECHANDY<<NATTHANIT<<<<<<<<<<<<<<<<<<",
            ]
        ),
    )

    assert corrected == "NATTHANIT MONECHANDY"


def test_printed_name_pair_does_not_replace_single_mrz_supported_name_with_over() -> None:
    corrected = MrzAnalyzer._corroborate_name_with_printed_fields(
        "ATTHANIT NONECHANDY",
        "\n".join(
            [
                "MONECHANDY",
                "OVER",
                "MONECHANDY",
                "NATTHANIT",
                "MOLAOMONECHANDY<<NA",
                "PA04906464NANDYSSNATTHANIT<<<<<",
            ]
        ),
    )

    assert corrected == "NATTHANIT MONECHANDY"


def test_rotated_mrz_combines_visual_prefix_with_check_digit_protected_tail() -> None:
    noisy_ocr = "\n".join(
        [
            "JHA",
            "ASHUTOSH",
            "B729",
            "PSINDIHAK<ASHUTOSHKKKKKKKKECKKKKKEELEEERERE",
            "B7298",
            "87298307<4 1ND7204069M33112043078859541223<10",
        ]
    )

    result = MrzAnalyzer().analyze(_context_stub(), ocr_text=noisy_ocr)

    assert result.mrz_valid is True
    assert result.mrz_check_digits_valid is True
    assert result.passport_number == "B7298307"
    assert result.full_name == "ASHUTOSH JHA"
    assert result.nationality == "IND"
    assert str(result.date_of_birth) == "1972-04-06"
    assert str(result.expiry_date) == "2033-11-20"


def test_rotated_mrz_combines_country_and_checksum_evidence_across_passes() -> None:
    noisy_ocr = "\n".join(
        [
            "JHA",
            "ASHUTOSH",
            "B729",
            "PSINDIMAK<ASHUTOSHKKKKKKKKKECKKKKCKEEECKKKRK",
            # This pass preserves the checksum-protected suffix but reads the
            # unprotected nationality as 14D instead of IND.
            "B7298307<114D7204069M33112043078859541223<10",
            # A complementary pass reads 1ND, corroborating IND, but damages
            # one optional-data digit and therefore cannot validate alone.
            "97<11ND7204069M33112043078859561223<10",
        ]
    )

    result = MrzAnalyzer().analyze(_context_stub(), ocr_text=noisy_ocr)

    assert result.mrz_valid is True
    assert result.mrz_check_digits_valid is True
    assert result.passport_number == "B7298307"
    assert result.full_name == "ASHUTOSH JHA"
    assert result.nationality == "IND"
    assert str(result.date_of_birth) == "1972-04-06"
    assert str(result.expiry_date) == "2033-11-20"


def test_lao_spaced_printed_number_fuses_with_checksum_protected_mrz_tail() -> None:
    noisy_ocr = "\n".join(
        [
            "LAO PDR",
            "PA 0490616",
            "MONECHANDY",
            "NATTHANIT",
            "P<LAOMONECHANDY<<NATTHANIT<<<<<<<<<<<<<<<<",
            # The document-number prefix is damaged, S is the expiry check
            # digit 5, K glyphs are blurred fillers, and G is composite 6.
            "A1ALAO9406199F330531S5KKKKKKKKKKKKK<G",
        ]
    )

    result = MrzAnalyzer().analyze(_context_stub(), ocr_text=noisy_ocr)

    assert result.mrz_valid is True
    assert result.mrz_check_digits_valid is True
    assert result.passport_number == "PA0490616"
    assert result.full_name == "NATTHANIT MONECHANDY"
    assert result.nationality == "LAO"
    assert str(result.date_of_birth) == "1994-06-19"
    assert str(result.expiry_date) == "2033-05-31"


def test_lao_spaced_printed_number_does_not_bypass_wrong_composite_digit() -> None:
    noisy_ocr = "\n".join(
        [
            "LAO PDR",
            "PA 0490616",
            "P<LAOMONECHANDY<<NATTHANIT<<<<<<<<<<<<<<<<",
            "A1ALAO9406199F330531S5KKKKKKKKKKKKK<3",
        ]
    )

    result = MrzAnalyzer().analyze(_context_stub(), ocr_text=noisy_ocr)

    assert result.mrz_valid is False
    assert result.mrz_check_digits_valid is False


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


def test_passport_with_weak_mrz_is_rejected_for_retake_even_with_visible_fields() -> None:
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

    assert analysis.status == "rejected"
    assert "MRZ_NOT_READ" not in {signal.code for signal in analysis.signals}
    assert "MRZ_NOT_CONFIDENT" in {signal.code for signal in analysis.signals}
    mrz_signal = next(signal for signal in analysis.signals if signal.code == "MRZ_NOT_CONFIDENT")
    assert "Retake" in mrz_signal.label
    assert "both MRZ lines fully visible" in mrz_signal.label
    assert analysis.checks["mrz_found"] is False
    assert analysis.checks["passport_text_evidence_score"] >= 0.65


def test_non_lao_passport_with_unvalidated_td3_fragments_is_rejected_for_retake() -> None:
    blurred_korean_passport_ocr = "\n".join(
        [
            "PASSPORT REPUBLIC OF KOREA",
            "PP KOR MS66S7652",
            "BYUNGCHUL",
            "03 MAY 1985",
            "KORIM<<BYUNGCHUL4466666660040000",
            "S66S776527K086505039M36051963101125V25670222",
        ]
    )

    analysis = PassportFraudAnalyzer().analyze(
        _passport_like_image(),
        "blurred-korean-passport.jpg",
        ocr_text=blurred_korean_passport_ocr,
    )

    assert analysis.status == "rejected"
    assert analysis.ocr.mrz_valid is False
    assert analysis.checks["mrz_found"] is False
    assert analysis.checks["mrz_soft_fallback"] is True
    assert "MRZ_NOT_CONFIDENT" in {signal.code for signal in analysis.signals}
    assert "MRZ_NOT_READ" not in {signal.code for signal in analysis.signals}


def test_malaysian_single_identifier_name_line_is_checksum_valid() -> None:
    malaysian_passport_ocr = "\n".join(
        [
            "PASSPORT MALAYSIA P MYS A56384584",
            "WAN DALILA DARMIELLIA BINTI W MUSTOFFA",
            "P<MYSWAN<DALILA<DARMIELLIA<BINTI<W<MUSTOFFA<",
            "A563845843MYS8905086F2708023890508075394<<42",
        ]
    )

    analysis = PassportFraudAnalyzer().analyze(
        _passport_like_image(),
        "malaysian-passport.jpg",
        ocr_text=malaysian_passport_ocr,
    )

    assert analysis.checks["mrz_found"] is True
    assert analysis.ocr.mrz_valid is True
    assert analysis.ocr.passport_number == "A56384584"
    assert analysis.ocr.nationality == "MYS"
    assert analysis.ocr.full_name == "WAN DALILA DARMIELLIA BINTI W MUSTOFFA"
    assert str(analysis.ocr.date_of_birth) == "1989-05-08"
    assert str(analysis.ocr.expiry_date) == "2027-08-02"


def test_invalid_flipped_mrz_does_not_mark_normal_document_as_mirrored() -> None:
    analyzer = PassportFraudAnalyzer()
    loaded = analyzer.loader.load(_passport_like_image(), "normal-passport.jpg")
    assert not isinstance(loaded, type(None))
    analyzer.ocr.extract = lambda *_args, **_kwargs: "\n".join(
        [
            "P<ITHNG<BYOSI<<IQTNIMBYO<<<<<<<<<<<<<<<<<<",
            "ATOTCUMPW0ITH9001011M3001011<<<<<<<<<<<<<<02",
        ]
    )

    analyzer._flag_if_mirrored(loaded, "unreadable upright OCR")

    assert loaded.checks.get("document_mirrored") is not True
    assert "DOCUMENT_MIRRORED" not in {signal.code for signal in loaded.signals}


def test_checksum_valid_flipped_mrz_marks_document_as_mirrored() -> None:
    analyzer = PassportFraudAnalyzer()
    loaded = analyzer.loader.load(_passport_like_image(), "mirrored-passport.jpg")
    assert not isinstance(loaded, type(None))
    analyzer.ocr.extract = lambda *_args, **_kwargs: "\n".join(
        [
            "P<MYSWAN<DALILA<DARMIELLIA<BINTI<W<MUSTOFFA<",
            "A563845843MYS8905086F2708023890508075394<<42",
        ]
    )

    analyzer._flag_if_mirrored(loaded, "unreadable mirrored OCR")

    assert loaded.checks["document_mirrored"] is True
    assert "DOCUMENT_MIRRORED" in {signal.code for signal in loaded.signals}


def test_two_letter_type_name_line_allows_tail_digit_noise_when_checks_validate() -> None:
    blurred_french_passport_ocr = "\n".join(
        [
            "REPUBLIQUE FRANCAISE PASSPORT",
            "PSFRAMEYRIGNAC<<ANTOINE<CARLOS<S<98",
            "21FV042155FRA7406195M3202137<<<<<<<<<<<<<<<<",
        ]
    )

    analysis = PassportFraudAnalyzer().analyze(
        _passport_like_image(),
        "blurred-french-passport.jpg",
        ocr_text=blurred_french_passport_ocr,
    )

    assert analysis.checks["mrz_found"] is True
    assert analysis.ocr.mrz_valid is True
    assert analysis.ocr.passport_number == "21FV04215"
    assert analysis.ocr.nationality == "FRA"
    assert str(analysis.ocr.date_of_birth) == "1974-06-19"
    assert str(analysis.ocr.expiry_date) == "2032-02-13"
    assert analysis.ocr.full_name == "ANTOINE CARLOS MEYRIGNAC"
    assert "MRZ_NOT_READ" not in {signal.code for signal in analysis.signals}


def test_complete_australian_mrz_outranks_partial_primary_check_collision() -> None:
    australian_passport_ocr = "\n".join(
        [
            "PASSPORT AUSTRALIA",
            "CAMROUX",
            "NOAH THOMAS",
            "P<AUSCAMROUX<<NOAH<THOMASS<<<<<<6<5<<595889<",
            "RA57177390AUS0512103M3405237<BG585090W<<<<42",
            "RAS7177390AUSO51210343405237<BG585090<<<<<<<",
        ]
    )

    analysis = PassportFraudAnalyzer().analyze(
        _passport_like_image(),
        "australian-passport.jpg",
        ocr_text=australian_passport_ocr,
    )

    assert analysis.ocr.mrz_valid is True
    assert analysis.ocr.passport_number == "RA5717739"
    assert analysis.ocr.full_name == "NOAH THOMAS CAMROUX"
    assert analysis.ocr.extracted_fields["sex"] == "M"
    assert analysis.ocr.extracted_fields["optional_check_digit_valid"] == "True"
    assert analysis.ocr.extracted_fields["composite_check_digit_valid"] == "True"


def test_missing_td3_prefix_is_recovered_from_validated_data_line_country() -> None:
    low_resolution_us_passport_ocr = "\n".join(
        [
            "PASSPORT UNITED STATES OF AMERICA",
            "WILLIAMS",
            "MAXIMILIAN PHILLIP ANTHONY",
            # Tesseract omitted P< and confused several name glyphs, but kept
            # the issuer and name-line structure.
            "USAWILLTANS<<HARTMEUTANSPHILLIP<ANTHONYSS567",
            "5679168123USA9012282M3003091717619085<859464",
        ]
    )

    analysis = PassportFraudAnalyzer().analyze(
        _passport_like_image(),
        "low-resolution-us-passport.jpg",
        ocr_text=low_resolution_us_passport_ocr,
    )

    assert analysis.checks["mrz_found"] is True
    assert analysis.ocr.mrz_valid is True
    assert analysis.ocr.passport_number == "567916812"
    assert analysis.ocr.nationality == "USA"
    assert str(analysis.ocr.date_of_birth) == "1990-12-28"
    assert str(analysis.ocr.expiry_date) == "2030-03-09"
    assert "MRZ_NOT_CONFIDENT" not in {signal.code for signal in analysis.signals}


def test_japanese_mrz_recovers_issuer_and_one_digit_from_independent_fields() -> None:
    japanese_passport_ocr = "\n".join(
        [
            "PASSPORT P JPN TT1444449",
            "HIDAKA",
            "YU",
            # P< became PS, JPN became IPN, and filler chevrons became digits.
            "PSIPNHIDAKAKKYUKKK<666666<<<6666EKRRKRRERKK",
            # The first document-number digit was read as 4 instead of 1.
            "TT44144495JPN7708132M3109074<<<<<<DA2",
        ]
    )

    analysis = PassportFraudAnalyzer().analyze(
        _passport_like_image(),
        "japanese-passport.jpg",
        ocr_text=japanese_passport_ocr,
    )

    assert analysis.checks["mrz_found"] is True
    assert analysis.ocr.mrz_valid is True
    assert analysis.ocr.passport_number == "TT1414449"
    assert analysis.ocr.nationality == "JPN"
    assert str(analysis.ocr.date_of_birth) == "1977-08-13"
    assert str(analysis.ocr.expiry_date) == "2031-09-07"
    assert analysis.ocr.full_name == "YU HIDAKA"
    assert "MRZ_NOT_CONFIDENT" not in {signal.code for signal in analysis.signals}


def test_dark_japanese_mrz_repairs_low_light_glyphs_with_visual_country() -> None:
    dark_japanese_passport_ocr = "\n".join(
        [
            "JPN",
            "HIDEAKI",
            # A separate OCR pass preserved one separator chevron and a clean
            # surname prefix, while adding one trailing glyph to each name.
            "DPIPNOGAKIC<HIDEAKLSSSSSKSKKKKKKEREKEEKEKS",
            # Genuine PP/JPN name line with J -> I and noisy filler glyphs.
            "PPIPNOGAKISENHIDEAK1R<56RK6RKKKKKKKKKEEESSKKK",
            # TM16165154/JPN/6010210/M/3512252, with M -> N, J -> 5,
            # and low-light digit substitutions G -> 6, D -> 0, S -> 3.
            "TN161651545PNGD1021OMSS122526K66666KKKKKKKID",
        ]
    )

    analysis = PassportFraudAnalyzer().analyze(
        _passport_like_image(),
        "dark-japanese-passport.jpg",
        ocr_text=dark_japanese_passport_ocr,
    )

    assert analysis.ocr.mrz_valid is True
    assert analysis.ocr.mrz_check_digits_valid is True
    assert analysis.ocr.passport_number == "TM1616515"
    assert analysis.ocr.nationality == "JPN"
    assert str(analysis.ocr.date_of_birth) == "1960-10-21"
    assert str(analysis.ocr.expiry_date) == "2035-12-25"
    assert analysis.ocr.full_name == "HIDEAKI OGAKI"
    assert "MRZ_CHECK_DIGIT_MISMATCH" not in {signal.code for signal in analysis.signals}


def test_soft_australian_mrz_combines_checked_number_and_clean_dates() -> None:
    soft_australian_passport_ocr = "\n".join(
        [
            "AUSTRALIA",
            "RB1160454",
            "WALTRAN",
            "TIMOTHYGEORG",
            "04 JAN 1993",
            "15 APR 2036",
            # One soft pass preserves the name tokens and correct document
            # number, but damages several date glyphs.
            "PRPAUSWALTRAN<<TIMOTHY<GEORG<KKKKKRKKKKCKK",
            "RB11604545AUS9S0104SM3604155<ELA2B41PPK<<<06",
            # Another pass reads all protected dates but changes R -> 9. The
            # clean number above carries the same ICAO document check digit.
            "PPAUSWALTRAN<<TIMOTHYCGEORG<KKKKKKKKKKKKKKKKM",
            "9B11604545AUS9301043N3604155<ELO2B41OP<<<<06",
        ]
    )

    analysis = PassportFraudAnalyzer().analyze(
        _passport_like_image(),
        "soft-australian-passport.jpg",
        ocr_text=soft_australian_passport_ocr,
    )

    assert analysis.ocr.mrz_valid is True
    assert analysis.ocr.passport_number == "RB1160454"
    assert analysis.ocr.nationality == "AUS"
    assert str(analysis.ocr.date_of_birth) == "1993-01-04"
    assert str(analysis.ocr.expiry_date) == "2036-04-15"
    assert analysis.ocr.full_name == "TIMOTHY GEORG WALTRAN"


def test_low_resolution_us_mrz_stitches_independently_checked_fields() -> None:
    low_resolution_us_passport_ocr = "\n".join(
        [
            "UNITED STATES OF AMERICA",
            "2 MAY",
            "AY",
            "ROBERTADEJUMO",
            # This pass preserves the checked document number and issuer but
            # loses the field boundary immediately after nationality.
            "6682281759USARTSADEJUMOR<<S<8KKK<<S00",
            # A separate pass drops the line prefix but reads the protected
            # birth, sex, expiry and optional-data suffix.
            "Q49106123M3106028619710450<696952",
            "PSUSAMAY<<ROBERT<ADEJU<<<<<<<<<<<<<<<<",
            "P<USAMAY<<4JNOBERT<ADEJUMO<<<<<<<<<<<<",
        ]
    )

    analysis = PassportFraudAnalyzer().analyze(
        _passport_like_image(),
        "low-resolution-us-passport.jpg",
        ocr_text=low_resolution_us_passport_ocr,
    )

    assert analysis.ocr.mrz_valid is True
    assert analysis.ocr.passport_number == "668228175"
    assert analysis.ocr.nationality == "USA"
    assert str(analysis.ocr.date_of_birth) == "1991-06-12"
    assert str(analysis.ocr.expiry_date) == "2031-06-02"
    assert analysis.ocr.full_name == "ROBERT ADEJUMO MAY"


def test_distant_portrait_thai_passport_mrz_is_parsed_from_mid_page_ocr() -> None:
    distant_thai_passport_ocr = "\n".join(
        [
            "KINGDOM OF THAILAND",
            "THUMMANEE",
            "THANITR",
            # Soft OCR from the middle identity-page band can introduce one
            # filler glyph beside the surname separator while preserving all
            # checksum-protected data fields.
            "PPTHATHUMMANEE<K<THANITR<<<<<<<<<<<<<<<<<<<<",
            "AD35008807THA7507047F36051743100601784751<92",
        ]
    )

    analysis = PassportFraudAnalyzer().analyze(
        _passport_like_image(),
        "distant-portrait-thai-passport.jpg",
        ocr_text=distant_thai_passport_ocr,
    )

    assert analysis.ocr.mrz_valid is True
    assert analysis.ocr.passport_number == "AD3500880"
    assert analysis.ocr.nationality == "THA"
    assert str(analysis.ocr.date_of_birth) == "1975-07-04"
    assert str(analysis.ocr.expiry_date) == "2036-05-17"
    assert analysis.ocr.full_name == "THANITR THUMMANEE"


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


def test_mrz_parser_preserves_valid_letter_in_alphanumeric_passport_number() -> None:
    mrz = "\n".join(
        [
            "P<ESPGUIJO<GARZON<<ALVARO<<<<<<<<<<<<<<<<<<<",
            "PAQ1722706ESP9007091M3302093A3206973500<<<10",
        ]
    )

    result = MrzAnalyzer().analyze(_context_stub(), ocr_text=mrz)

    assert result.mrz_valid is True
    assert result.mrz_check_digits_valid is True
    assert result.passport_number == "PAQ172270"
    assert result.nationality == "ESP"


def test_mrz_parser_discards_leading_noise_before_td3_type_marker() -> None:
    noisy_ocr = "\n".join(
        [
            "MISS AISAWAN",
            "7P<THAPRAKOBKARN<<AISAWANS<<<<<KK<K<KKKKKKKK",
            "AC73487656THA8310257F34092463400100423974<38",
        ]
    )

    result = MrzAnalyzer().analyze(_context_stub(), ocr_text=noisy_ocr)

    assert result.mrz_valid is True
    assert result.passport_number == "AC7348765"
    assert result.full_name == "AISAWAN PRAKOBKARN"
    assert result.nationality == "THA"
    assert str(result.date_of_birth) == "1983-10-25"
    assert str(result.expiry_date) == "2034-09-24"


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


def test_mrz_name_extraction_keeps_suffixed_surname_and_multipart_given() -> None:
    # "WALKER JR" ends with a short token right before the "<<" separator --
    # the island-filler heuristic must not learn "JR" as filler and clip the
    # surname to "WALKE" (US-passport style suffixed surnames).
    mrz = "\n".join(
        [
            "P<USAWALKER<JR<<STEPHEN<WELCH<<<<<<<<<<<<<<<",
            "6424847838USA8203313M2810294293402887<107580",
        ]
    )
    result = MrzAnalyzer().analyze(_context_stub(), ocr_text=mrz)

    assert result.mrz_valid is True
    assert result.full_name == "STEPHEN WELCH WALKER JR"
    assert result.passport_number == "642484783"
    assert result.nationality == "USA"
    assert str(result.date_of_birth) == "1982-03-31"
    assert str(result.expiry_date) == "2028-10-29"
