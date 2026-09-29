#!/usr/bin/env python3
"""Build the Kyron eKYC white paper as a black-and-white Word document.

Deliberately monochrome: black text on white, greyscale rules and table
shading only -- no colour anywhere, so it prints and photocopies cleanly and
suits formal/regulator distribution.

    .venv/bin/python scripts/build_kyron_white_paper_docx.py
"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs" / "kyron-ekyc-white-paper.docx"

BLACK = RGBColor(0, 0, 0)
GREY = RGBColor(0x59, 0x59, 0x59)
HEADER_FILL = "E6E6E6"   # greyscale only
BODY_FONT = "Calibri"


# ---------------------------------------------------------------- primitives
def style_run(run, *, size=10.5, bold=False, italic=False, color=BLACK, name=BODY_FONT):
    run.font.name = name
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs"):
        rfonts.set(qn(attr), name)


def para(doc, text="", *, size=10.5, bold=False, italic=False, color=BLACK,
         before=0, after=6, align=None, line=1.15, indent=None):
    p = doc.add_paragraph()
    if align is not None:
        p.alignment = align
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = line
    if indent is not None:
        pf.left_indent = Inches(indent)
    if text:
        style_run(p.add_run(text), size=size, bold=bold, italic=italic, color=color)
    return p


def rich(doc, segments, *, size=10.5, after=6, before=0, align=None, line=1.15):
    """A paragraph built from (text, bold, italic) segments."""
    p = doc.add_paragraph()
    if align is not None:
        p.alignment = align
    pf = p.paragraph_format
    pf.space_before, pf.space_after, pf.line_spacing = Pt(before), Pt(after), line
    for seg in segments:
        text, bold, italic = (seg + (False, False))[:3] if isinstance(seg, tuple) else (seg, False, False)
        style_run(p.add_run(text), size=size, bold=bold, italic=italic)
    return p


def heading(doc, text, level=1):
    sizes = {1: 14, 2: 11.5, 3: 10.5}
    p = para(doc, text, size=sizes.get(level, 11), bold=True,
             before=14 if level == 1 else 10, after=4,
             italic=(level == 3))
    if level == 1:
        rule(p)
    return p


def rule(paragraph, *, size="6", color="000000"):
    ppr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), size)
    bottom.set(qn("w:space"), "3")
    bottom.set(qn("w:color"), color)
    borders.append(bottom)
    ppr.append(borders)


def bullet(doc, text, *, bold_lead=None):
    p = doc.add_paragraph(style="List Bullet")
    pf = p.paragraph_format
    pf.space_before, pf.space_after, pf.line_spacing = Pt(0), Pt(3), 1.15
    if bold_lead:
        style_run(p.add_run(bold_lead), size=10.5, bold=True)
    style_run(p.add_run(text), size=10.5)
    return p


def numbered(doc, text):
    p = doc.add_paragraph(style="List Number")
    pf = p.paragraph_format
    pf.space_before, pf.space_after, pf.line_spacing = Pt(0), Pt(3), 1.15
    style_run(p.add_run(text), size=10.5)
    return p


def shade(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def cell_text(cell, text, *, bold=False, size=9.5, align=None):
    cell.text = ""
    p = cell.paragraphs[0]
    if align is not None:
        p.alignment = align
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after = Pt(3)
    style_run(p.add_run(text), size=size, bold=bold)


def table(doc, headers, rows, widths, *, caption=None):
    if caption:
        para(doc, caption, size=9, italic=True, color=GREY, after=3)
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for idx, head in enumerate(headers):
        c = t.rows[0].cells[idx]
        cell_text(c, head, bold=True)
        shade(c, HEADER_FILL)
    for row in rows:
        cells = t.add_row().cells
        for idx, value in enumerate(row):
            align = WD_ALIGN_PARAGRAPH.RIGHT if idx and str(value).strip().endswith("%") else None
            cell_text(cells[idx], str(value), align=align)
    for row in t.rows:
        for idx, c in enumerate(row.cells):
            c.width = Inches(widths[idx])
    para(doc, "", after=6)
    return t


def callout(doc, title, body):
    """Bordered greyscale note box."""
    t = doc.add_table(rows=1, cols=1)
    t.style = "Table Grid"
    cell = t.rows[0].cells[0]
    cell.text = ""
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(4)
    style_run(p.add_run(f"{title}  "), size=10, bold=True)
    style_run(p.add_run(body), size=10, italic=True)
    cell.width = Inches(6.5)
    para(doc, "", after=8)


def add_page_numbers(section):
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    for instr, txt in (("begin", None), (None, "PAGE"), ("end", None)):
        if instr == "begin":
            fld = OxmlElement("w:fldChar"); fld.set(qn("w:fldCharType"), "begin"); run._r.append(fld)
        elif instr == "end":
            fld = OxmlElement("w:fldChar"); fld.set(qn("w:fldCharType"), "end"); run._r.append(fld)
        else:
            it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve"); it.text = txt
            run._r.append(it)
    style_run(run, size=9, color=GREY)


# ---------------------------------------------------------------- document
def build() -> None:
    doc = Document()
    s = doc.sections[0]
    s.top_margin = s.bottom_margin = Inches(1)
    s.left_margin = s.right_margin = Inches(1)
    add_page_numbers(s)

    normal = doc.styles["Normal"]
    normal.font.name = BODY_FONT
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = BLACK

    # ---- Title block
    para(doc, "TECHNICAL WHITE PAPER", size=9, bold=True, color=GREY, after=10, align=WD_ALIGN_PARAGRAPH.CENTER)
    para(doc, "Kyron eKYC: A Robust, Explainable, IAL2-Aligned Pipeline "
              "for Remote Identity Proofing and Face Login",
         size=19, bold=True, after=10, align=WD_ALIGN_PARAGRAPH.CENTER, line=1.05)
    para(doc, "Kyron Research Team", size=11, bold=True, after=2, align=WD_ALIGN_PARAGRAPH.CENTER)
    p = para(doc, "⟨author names⟩  ·  ⟨affiliation⟩  ·  ⟨corresponding e-mail⟩",
             size=9.5, italic=True, color=GREY, after=4, align=WD_ALIGN_PARAGRAPH.CENTER)
    para(doc, "Draft v1.0  ·  July 2026", size=9.5, color=GREY, after=10, align=WD_ALIGN_PARAGRAPH.CENTER)
    rule(p)

    callout(doc, "Disclaimer.",
            "Kyron is designed toward NIST SP 800-63A IAL2 alignment. This paper does not claim NIST, ISO, "
            "bank-grade, or government certification. All quantitative results are measured on the datasets "
            "described in Section 7 and are operating-point estimates pending a larger, independently "
            "labelled validation study.")

    # ---- Abstract
    heading(doc, "Abstract", 1)
    para(doc, "Remote (unsupervised) identity proofing must simultaneously read and validate a government "
              "identity document, establish that a live human — not a photograph, screen, or mask — is "
              "present, and bind that human to the document portrait, all from consumer cameras under "
              "uncontrolled lighting and capture conditions. We present Kyron eKYC, a web-first pipeline "
              "(Python/FastAPI backend, React/Vite client) that composes document fraud detection, ICAO 9303 "
              "machine-readable-zone (MRZ) reading, passive presentation-attack detection (PAD), browser-side "
              "active liveness, and face matching into a single explainable risk decision aligned to NIST "
              "SP 800-63A Identity Assurance Level 2. We describe the architecture and, in particular, a set of "
              "robustness fixes that materially improve real-world read rates: correct handling of ICAO "
              "two-letter document types, MRZ-crop super-resolution, conditional illumination normalization, "
              "positional re-alignment of the OCR name line, and a mirrored-document detector. On a 150-image "
              "passport benchmark, MRZ detection rises from 52.9% to 67.3% and fully check-digit-valid reads "
              "from 35.1% to 46.0%; conditional on a valid read, date-of-birth and sex accuracy are 100%, "
              "expiry 99%, and document number 93%. For selfie capture, face-region light metering plus a "
              "low-light rescue path raise dark-room face detection from 25% to 95% with no regression on "
              "well-lit images. We discuss privacy-preserving data handling, the IAL2 alignment matrix, and "
              "the hardening required before formal certification.", align=WD_ALIGN_PARAGRAPH.JUSTIFY)
    rich(doc, [("Keywords: ", True, False),
               ("identity proofing, eKYC, NIST IAL2, presentation attack detection, liveness, MRZ/OCR, "
                "face recognition, ISO/IEC 30107.", False, True)], size=10)

    # ---- 1 Introduction
    heading(doc, "1.  Introduction", 1)
    para(doc, "Digital onboarding for banking, telecom, and government services increasingly relies on remote "
              "identity proofing: a user, alone with a phone or laptop, presents an identity document and their "
              "face, and an automated system decides whether to trust the claimed identity. Unlike supervised "
              "(in-person) proofing, the system cannot control lighting, camera quality, document handling, or "
              "the presence of an operator to detect obvious spoofs. The adversary, by contrast, can present "
              "printed photos, replayed video, screen captures, masks, and tampered or substituted documents.",
         align=WD_ALIGN_PARAGRAPH.JUSTIFY)
    para(doc, "This paper describes Kyron eKYC, a prototype that treats remote proofing as a composition of "
              "independent, individually-explainable checks rather than a single black-box classifier. Each "
              "stage emits typed reason codes and calibrated risk contributions, and the final decision is an "
              "auditable function of those signals. This design is motivated by two requirements that pure "
              "end-to-end models struggle to satisfy: regulatory expectations for explainability and redress, "
              "and operational debuggability when a genuine user is wrongly rejected.",
         align=WD_ALIGN_PARAGRAPH.JUSTIFY)
    para(doc, "In summary, the contributions of this paper are:", after=4)
    for item in [
        "An explainable, standards-aligned pipeline spanning document fraud detection, MRZ/OCR, passive and "
        "active liveness, and face matching, with a per-signal risk model (Sections 3–5).",
        "Robustness engineering for real-world capture (Section 6): six OCR/MRZ correctness and legibility "
        "fixes and a two-part lighting-robustness change, each isolated and measured.",
        "An empirical evaluation (Section 7) on document, spoof, and liveness datasets, reporting before/after "
        "effects of each change and honest failure analysis.",
        "A NIST IAL2 alignment matrix and hardening roadmap (Sections 8–10) separating what is demonstrated "
        "from what remains for certification.",
    ]:
        numbered(doc, item)

    # ---- 2 Standards
    heading(doc, "2.  Background and Standards Basis", 1)
    para(doc, "Kyron is designed against four normative references.", after=4)
    bullet(doc, "requires validation of strong or superior evidence, verification that the evidence belongs to "
                "the applicant (typically a biometric comparison with liveness), and fraud/duplicate checks.",
           bold_lead="NIST SP 800-63A ")
    bullet(doc, "defines the TD3 passport MRZ: two 44-character lines, field offsets, the 7-3-1 weighted "
                "check-digit scheme, and the composite check, implemented directly by our reader.",
           bold_lead="ICAO Doc 9303 ")
    bullet(doc, "frames PAD evaluation via the Attack and Bona-fide Presentation Classification Error Rates "
                "(APCER, BPCER).", bold_lead="ISO/IEC 30107-3 ")
    bullet(doc, "motivates risk-based assurance, auditability, and ongoing monitoring, reflected in the "
                "reason-code and audit design.", bold_lead="FATF Digital ID guidance ")

    # ---- 3 Architecture
    heading(doc, "3.  System Architecture", 1)
    heading(doc, "3.1  End-to-end flow", 2)
    for step in [
        "Document capture (passport / Lao ID) → quality, document-likeness, MRZ/OCR, forensics, fraud "
        "ensemble. A rejection returns a specific reason code and a retake prompt.",
        "Active liveness → randomized blink / open-mouth / head-turn challenges, with backend-verified "
        "evidence bursts.",
        "Randomized hand-gesture challenge → three of 23 gestures, easy-weighted.",
        "Selfie passive liveness and face match → 10-frame burst; YuNet + SFace against the document portrait.",
        "Risk decision → typed reason codes, then optional Face ID enrollment and returning-user face login.",
    ]:
        numbered(doc, step)
    heading(doc, "3.2  Design principles", 2)
    bullet(doc, "every stage is independently testable and emits reason codes; the decision layer is a "
                "transparent aggregation, not a learned end-to-end score.", bold_lead="Composition over monolith: ")
    bullet(doc, "latency- and privacy-sensitive work runs in the browser; trust-bearing decisions run "
                "server-side so a modified client cannot forge them.", bold_lead="Client/edge split: ")
    bullet(doc, "a rejection always carries a human-actionable reason rather than a bare score.",
           bold_lead="Fail-explainable: ")
    bullet(doc, "raw document and selfie images are not persisted during verification; only transient face "
                "embeddings live in session state.", bold_lead="Privacy by construction: ")
    heading(doc, "3.3  Implementation", 2)
    para(doc, "The backend is Python/FastAPI with service boundaries for document fraud, model-style document "
              "adapters, face biometrics and PAD, and selfie aggregation; profiles persist via SQLAlchemy "
              "(SQLite locally, PostgreSQL in deployment). The frontend is React/Vite with in-browser MediaPipe "
              "FaceMesh and Hands. OCR uses Tesseract; detection and recognition use OpenCV YuNet and SFace; "
              "PAD uses an ONNX MiniFASNet-family ensemble with heuristic corroboration.",
         align=WD_ALIGN_PARAGRAPH.JUSTIFY)

    # ---- 4 Methods
    heading(doc, "4.  Methods", 1)
    heading(doc, "4.1  Document quality, likeness, and forensics", 2)
    para(doc, "Before OCR, each upload is scored for resolution, brightness, contrast, sharpness, glare, and "
              "document-likeness (edge density, rectangularity) to reject non-document uploads. Forensic "
              "analyzers estimate recapture risk, tamper risk, and portrait substitution — a genuine body and "
              "MRZ with a swapped photo — via saturation and noise discontinuities in the portrait region "
              "conditioned on MRZ validity. A heuristic and optional-ONNX ensemble fuses these into a "
              "fraud-risk score.", align=WD_ALIGN_PARAGRAPH.JUSTIFY)
    heading(doc, "4.2  MRZ / OCR (ICAO TD3)", 2)
    para(doc, "Passport reading parses TD3 field offsets and validates the document-number, birth-date, expiry, "
              "optional, and composite check digits with 7-3-1 weighting. Validity is anchored on the "
              "check-digit-protected line-2 data, so document number, date of birth, and expiry are trustworthy "
              "whenever the MRZ is valid; the alphabetic line-1 name field, which carries no check digit, is "
              "best-effort and corrected by the methods in Section 6.", align=WD_ALIGN_PARAGRAPH.JUSTIFY)
    heading(doc, "4.3  Passive liveness (PAD)", 2)
    para(doc, "The selfie stage captures a 10-frame burst and aggregates per-frame PAD, combining a "
              "MiniFASNet-family model with corroborating heuristics for screen borders, display-surface "
              "moiré, paper-photo texture, and hand-held-phone cues, plus temporal burst checks (near-static "
              "frames or absent natural brightness variation indicate a replay). A single-frame model spike is "
              "deliberately not sufficient to reject a bona-fide user.", align=WD_ALIGN_PARAGRAPH.JUSTIFY)
    heading(doc, "4.4  Active liveness (challenge–response)", 2)
    para(doc, "The client runs MediaPipe FaceMesh and issues randomized action challenges — blink, open mouth, "
              "turn left or right — detected from landmark geometry (eye-aspect ratio, mouth-open ratio, and a "
              "nose-offset yaw estimate). On detection the client sends a short evidence burst to the backend, "
              "which re-runs face detection and PAD so that a challenge cannot be satisfied by a modified client "
              "alone. A randomized hand-gesture challenge adds an interaction that is expensive to pre-render "
              "for replay.", align=WD_ALIGN_PARAGRAPH.JUSTIFY)
    heading(doc, "4.5  Face matching and Face ID", 2)
    para(doc, "Face matching uses OpenCV YuNet detection and SFace embeddings, comparing the live selfie "
              "embedding to the document-portrait embedding by cosine similarity against a pass threshold, with "
              "a borderline band that raises a medium signal. On a passed session, exactly one active face "
              "template is enrolled per user and one verified profile per document number, enabling "
              "returning-user face login that re-checks passive liveness before matching.",
         align=WD_ALIGN_PARAGRAPH.JUSTIFY)

    # ---- 5 Threat model
    heading(doc, "5.  Threat Model", 1)
    para(doc, "We assume a remote attacker who may present a printed photo, photocopy, or scan of a genuine "
              "document; replay a screen or video of a face; wear a paper or cutout mask; present a tampered or "
              "portrait-substituted document; hold a phone or tablet screen to the camera; or exploit capture "
              "artifacts such as front-camera mirroring and extreme back-light to slip a spoof through as "
              "“just poor quality”. We do not claim defense against high-fidelity 3-D masks, injection attacks "
              "on a compromised device or operating system, or coerced-genuine-user scenarios; these are out of "
              "scope for a software-only prototype.", align=WD_ALIGN_PARAGRAPH.JUSTIFY)

    # ---- 6 Robustness
    heading(doc, "6.  Robustness Engineering", 1)
    para(doc, "Field testing surfaced that the dominant cause of bona-fide failures was not the models but the "
              "capture front-end: real documents that would not read, and real faces that would not detect, "
              "under ordinary phone-camera conditions. We isolated and measured six document/MRZ fixes and one "
              "two-part lighting fix.", align=WD_ALIGN_PARAGRAPH.JUSTIFY)
    for title, body in [
        ("6.1  ICAO two-letter document-type acceptance",
         "The MRZ line-1 selector required a “P<” prefix, silently rejecting every passport whose type "
         "sub-category is a letter (Lao PO, diplomatic PD, service PS) before any check digit was evaluated. "
         "Acceptance was broadened to P plus a filler or letter plus a three-letter issuing country, with a "
         "digit-count guard separating the alphabetic name line from the numeric data line. This was the single "
         "largest driver of the read-rate gain."),
        ("6.2  MRZ-crop super-resolution",
         "Dataset images are small (median 726 px wide), so a TD3 glyph is only 6–10 px tall — near the OCR "
         "engine's floor. MRZ crops are upscaled with smooth fractional LANCZOS resampling to roughly 2600 px on "
         "the long side, and upright bottom-band crops were added to a region set that was previously "
         "rotation-only."),
        ("6.3  Conditional illumination normalization",
         "Dark or washed-out captures are normalized (CLAHE plus a gamma pull toward mid-tone) before OCR. "
         "Normalization is conditional: well-exposed images stay on the original path, after unconditional CLAHE "
         "was observed to over-sharpen already-crisp glyphs and induce errors. Enhancement must be gated to the "
         "regime it helps."),
        ("6.4  Line-1 re-alignment and filler-letter stripping",
         "Because line 1 carries no check digit, OCR noise there is uncorrected. A doubled leading type "
         "character, which shifts the country code and every name character one place to the right, is detected "
         "and realigned; and where the deep-filler tail is dominated by one letter, a single trailing instance "
         "that bled onto a name token is stripped."),
        ("6.5  Nationality cross-fill",
         "The nationality field on line 2 and the issuing country on line 1 are the same ICAO three-letter code. "
         "When OCR mangles the line-2 value into non-letters but the line-1 issuer is clean, the issuer is used."),
        ("6.6  Mirrored-document detection",
         "Front (selfie) cameras horizontally flip the frame, so a held document reads backwards and never "
         "parses. On the failure path only, the reader re-reads a horizontally-flipped copy; if the flip yields "
         "a valid MRZ, or produces markedly more MRZ filler characters than the original, the document was "
         "mirrored and a specific retake signal is emitted instead of a generic “MRZ not read”."),
        ("6.7  Lighting robustness for selfies",
         "Brightness, contrast, and glare are metered on the detected face crop rather than the whole frame, so "
         "a bright background behind a dark, back-lit face is correctly diagnosed. When face detection fails or "
         "the frame is under-exposed, detection and embedding are retried on an illumination-normalized copy; "
         "normalization is geometry-preserving, so the face box stays valid for PAD, which remains on the "
         "original image to avoid disturbing spoof cues."),
    ]:
        heading(doc, title, 2)
        para(doc, body, align=WD_ALIGN_PARAGRAPH.JUSTIFY)

    # ---- 7 Evaluation
    heading(doc, "7.  Evaluation", 1)
    heading(doc, "7.1  Datasets", 2)
    para(doc, "Evaluation uses the project's labelled sets: a passport corpus of 864 image/ground-truth pairs "
              "(820 passports and 44 face-only or non-passport images), selfie passive-liveness and face-login "
              "sets, an active-liveness attack set, and print-copy document attacks. Passport ground truth is "
              "taken from the MRZ lines, which are canonical and unambiguous, rather than the noisier printed "
              "fields.", align=WD_ALIGN_PARAGRAPH.JUSTIFY)

    heading(doc, "7.2  Passport MRZ / OCR read rate", 2)
    table(doc,
          ["Metric", "Baseline", "With fixes", "Change"],
          [["MRZ detected (readable)", "52.9%", "67.3%", "+14.4 pp"],
           ["MRZ fully valid (all check digits)", "35.1%", "46.0%", "+10.9 pp"],
           ["Passport number", "34.9%", "46.7%", "+11.8 pp"],
           ["Date of birth", "42.7%", "57.3%", "+14.6 pp"],
           ["Expiry date", "43.8%", "59.1%", "+15.3 pp"]],
          [2.6, 1.3, 1.3, 1.3],
          caption="Table 1. 150-image passport sample, all Section 6 document fixes versus the pre-fix baseline "
                  "(pp = percentage points).")
    para(doc, "Conditional accuracy — given a fully-valid MRZ — confirms the parser is sound and that the "
              "ceiling is OCR legibility rather than logic: date of birth 100%, sex 100%, expiry 99%, passport "
              "number 93%, and nationality 83–91%. Face-only and non-passport images are correctly not read as "
              "passports 85–88% of the time, and mirrored documents are rejected with a specific reason code. "
              "Remaining non-reads are dominated by capture geometry — hand-held photos at arbitrary angles and "
              "glare — which super-resolution cannot recover.", align=WD_ALIGN_PARAGRAPH.JUSTIFY)

    heading(doc, "7.3  Selfie presentation-attack detection", 2)
    para(doc, "Corroboration-based aggregation eliminated a systematic bona-fide failure: real faces wearing "
              "eyeglasses previously triggered a held-phone or screen false-reject at approximately 43%; after "
              "requiring recurrence plus model corroboration, this fell to 0% while screen and photo spoofs "
              "continued to be rejected at the prior rate in the tested sets. A back-light and over-exposure "
              "diagnosis converts a class of silent PAD false-rejects into actionable retake guidance.",
         align=WD_ALIGN_PARAGRAPH.JUSTIFY)

    heading(doc, "7.4  Active-liveness anti-spoof gate", 2)
    para(doc, "On collected attacks, the server-side gate — small-face rejection plus a recurring PAD-model vote "
              "over three-frame bursts — rejected printed-photo attacks (120 images / 40 bursts) and "
              "phone-screen replay (50 images / 17 bursts) at 100%, with 0% false-accept.",
         align=WD_ALIGN_PARAGRAPH.JUSTIFY)

    heading(doc, "7.5  Lighting robustness", 2)
    table(doc,
          ["Condition", "Baseline", "With fix"],
          [["Dim room (×0.18 brightness)", "75%", "100%"],
           ["Very dark (×0.12 brightness)", "25%", "95%"]],
          [3.0, 1.75, 1.75],
          caption="Table 2. Face-detection success on 20 genuine selfies synthetically darkened to simulate a "
                  "dim room.")
    para(doc, "Well-lit images were unchanged (20 of 20 detected, embeddings untouched), so there is no "
              "regression on the common case — the rescue path activates only for images that were already "
              "failing.", align=WD_ALIGN_PARAGRAPH.JUSTIFY)
    callout(doc, "On headline figures.",
            "Earlier collateral cites approximately 95.7% document and 96.4% liveness accuracy. These remain "
            "target/operating-point estimates pending a study of at least 10,000 samples per category and are "
            "not claimed as validated here. The figures in Section 7 are the directly measured results of this "
            "work.")

    # ---- 8 IAL2
    heading(doc, "8.  NIST IAL2 Alignment and Assurance", 1)
    table(doc,
          ["IAL2 obligation", "Kyron mechanism", "Status"],
          [["Validate strong evidence", "TD3 MRZ with check digits; quality and forensics; fraud ensemble",
            "Demonstrated (prototype)"],
           ["Evidence belongs to applicant", "Face match (YuNet + SFace), selfie to document portrait",
            "Demonstrated"],
           ["Presence / anti-spoof", "Passive PAD burst, active challenge–response, backend evidence bursts",
            "Demonstrated; APCER/BPCER not yet certified"],
           ["Fraud / duplicate checks", "Portrait-substitution, recapture and tamper signals; one profile per "
            "document number", "Partial"],
           ["Explainability / redress", "Typed reason codes; admin audit view",
            "Prototype; manual review pending"]],
          [1.9, 2.7, 1.9],
          caption="Table 3. IAL2 obligations mapped to Kyron mechanisms and prototype status.")
    heading(doc, "8.1  Privacy and data handling", 2)
    para(doc, "During verification, Kyron does not persist raw document or selfie images; it holds only "
              "transient face embeddings in session state. On a passed session it stores one face template plus "
              "a minimal verified profile (document number, name, nationality, birth date and age, and expiry). "
              "Session state is short-lived and client-bound by a per-session token to defeat identifier-only "
              "replay or hijack.", align=WD_ALIGN_PARAGRAPH.JUSTIFY)
    heading(doc, "8.2  Remaining hardening for certification", 2)
    for item in [
        "Encrypted, revocable biometric-template storage with key rotation.",
        "Explicit consent capture, retention limits, and deletion or export on request.",
        "Authenticated admin APIs and tamper-evident, exportable audit logging.",
        "Independent PAD validation against ISO/IEC 30107-3 with reported APCER and BPCER.",
        "Threshold calibration from large labelled sets, with fairness analysis.",
        "Manual review and redress workflow; multi-factor authentication for high-value actions.",
        "Third-party security and privacy assessment.",
    ]:
        bullet(doc, item)

    # ---- 9 Limitations
    heading(doc, "9.  Limitations and Threats to Validity", 1)
    bullet(doc, "Section 7 uses hundreds, not tens of thousands, of images, and some are synthetically "
                "perturbed; absolute rates will shift on larger, field-representative data.",
           bold_lead="Sample size and provenance. ")
    bullet(doc, "Using the MRZ as ground truth measures OCR fidelity to the printed MRZ, not to civil-registry "
                "identity.", bold_lead="Ground truth. ")
    bullet(doc, "Heuristic corroboration is tuned to observed attacks; novel display hardware and high-fidelity "
                "masks are not represented.", bold_lead="PAD generalization. ")
    bullet(doc, "Camera or operating-system injection, deepfake video injection, and coerced-genuine-user cases "
                "are not addressed by a software-only client.", bold_lead="Out-of-scope attacks. ")

    # ---- 10 Future work
    heading(doc, "10.  Future Work", 1)
    for item in [
        "MRZ localization and perspective rectification — the highest-return change for the passports that "
        "still fail to read.",
        "Independent PAD benchmarking with reported APCER and BPCER against a bona-fide error budget.",
        "Calibrated, per-population thresholds for face match and passive risk, with fairness analysis across "
        "demographics and eyewear.",
        "Deepfake and injection resistance through device attestation, signed capture, and challenge entropy.",
        "A large labelled validation study to convert target headline figures into certified operating points.",
    ]:
        numbered(doc, item)

    # ---- 11 Conclusion
    heading(doc, "11.  Conclusion", 1)
    para(doc, "Kyron eKYC shows that a composed, explainable remote-proofing pipeline can be made materially "
              "more robust to real-world capture without sacrificing spoof resistance, by fixing the front-end "
              "failure modes that dominate bona-fide rejections: document-type handling, MRZ legibility, "
              "mirrored capture, and lighting. The measured gains — passport read validity from 35% to 46%, "
              "dark-room face detection from 25% to 95%, and elimination of the eyeglass PAD false-reject, all "
              "without regressions on the well-behaved case — argue for treating capture robustness as a "
              "first-class engineering target alongside model accuracy. The path to certification is a "
              "disciplined hardening and independent-validation program, not a change of architecture.",
         align=WD_ALIGN_PARAGRAPH.JUSTIFY)

    # ---- References
    heading(doc, "References", 1)
    for idx, ref in enumerate([
        "NIST, SP 800-63A: Digital Identity Guidelines — Enrollment and Identity Proofing.",
        "ICAO, Doc 9303: Machine Readable Travel Documents, Parts 3–4 (TD3).",
        "ISO/IEC 30107-3, Biometric presentation attack detection — Part 3: Testing and reporting.",
        "FATF, Guidance on Digital Identity.",
        "J. Deng et al., ArcFace / SFace face representation.",
        "W. Wu et al., YuNet: A Tiny Millisecond-level Face Detector.",
        "Google, MediaPipe Face Mesh and Hands.",
        "MiniFASNet / Silent-Face anti-spoofing family (ONNX).",
    ], start=1):
        para(doc, f"[{idx}]  {ref}", size=9.5, after=3)
    para(doc, "Replace indicative references with full citations before external release.",
         size=9, italic=True, color=GREY, before=4)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUTPUT)
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    build()
