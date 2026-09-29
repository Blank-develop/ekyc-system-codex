from __future__ import annotations

from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path("/Users/chilanhouthnitvongkhay/Downloads/ekyc-system-codex")
OUT_DIR = ROOT / "outputs" / "project_proposal"
SCREEN_DIR = OUT_DIR / "screenshots"
PDF_PATH = OUT_DIR / "LALIGENCE_eKYC_Project_Proposal.pdf"
LOGO = ROOT / "logo.png"

NAVY = colors.HexColor("#081632")
BLUE = colors.HexColor("#2E74B5")
DARK_BLUE = colors.HexColor("#1F4D78")
MUTED = colors.HexColor("#5F6F8B")
GOLD = colors.HexColor("#E7BF35")
LIGHT_BLUE = colors.HexColor("#F4F6F9")
LIGHT_GOLD = colors.HexColor("#FFF7DE")
BORDER = colors.HexColor("#D8E0EE")


styles = getSampleStyleSheet()
styles.add(ParagraphStyle("CoverTitle", fontName="Helvetica-Bold", fontSize=25, leading=29, textColor=NAVY, alignment=TA_CENTER, spaceAfter=8))
styles.add(ParagraphStyle("CoverSub", fontName="Helvetica", fontSize=12.5, leading=17, textColor=MUTED, alignment=TA_CENTER, spaceAfter=22))
styles.add(ParagraphStyle("H1x", fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=BLUE, spaceBefore=16, spaceAfter=8))
styles.add(ParagraphStyle("H2x", fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=BLUE, spaceBefore=11, spaceAfter=6))
styles.add(ParagraphStyle("Bodyx", fontName="Helvetica", fontSize=10.2, leading=14.2, textColor=NAVY, spaceAfter=7))
styles.add(ParagraphStyle("Mutedx", fontName="Helvetica-Oblique", fontSize=8.8, leading=11, textColor=MUTED, alignment=TA_CENTER, spaceAfter=10))
styles.add(ParagraphStyle("CalloutTitle", fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=NAVY, spaceAfter=3))
styles.add(ParagraphStyle("CalloutBody", fontName="Helvetica", fontSize=9.8, leading=13, textColor=NAVY))


def p(text: str, style="Bodyx"):
    return Paragraph(text, styles[style])


def bullets(items):
    return ListFlowable(
        [ListItem(p(item), leftIndent=8) for item in items],
        bulletType="bullet",
        leftIndent=18,
        bulletFontName="Helvetica",
        bulletFontSize=8,
        bulletColor=GOLD,
    )


def numbers(items):
    return ListFlowable(
        [ListItem(p(item), leftIndent=8) for item in items],
        bulletType="1",
        leftIndent=18,
        bulletFontName="Helvetica-Bold",
        bulletFontSize=9,
        bulletColor=BLUE,
    )


def table(data, col_widths):
    flow = Table(data, colWidths=col_widths, hAlign="LEFT", repeatRows=1)
    flow.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), NAVY),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("LEADING", (0, 0), (-1, -1), 10.5),
        ("GRID", (0, 0), (-1, -1), 0.45, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return flow


def callout(title, body):
    flow = Table([[p(title, "CalloutTitle"), p(body, "CalloutBody")]], colWidths=[1.35 * inch, 5.0 * inch])
    flow.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GOLD),
        ("BOX", (0, 0), (-1, -1), 0.5, GOLD),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return flow


def screenshot(title, file_name, caption):
    img = Image(str(SCREEN_DIR / file_name), width=6.4 * inch, height=4.35 * inch)
    img.hAlign = "CENTER"
    return KeepTogether([p(title, "H2x"), img, p(caption, "Mutedx")])


def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(0.75 * inch, 0.45 * inch, "LALIGENCE eKYC Project Proposal")
    canvas.drawRightString(7.75 * inch, 0.45 * inch, f"Page {doc.page}")
    canvas.restoreState()


def build():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(PDF_PATH), pagesize=letter, rightMargin=0.75 * inch, leftMargin=0.75 * inch, topMargin=0.74 * inch, bottomMargin=0.74 * inch)
    story = []

    logo = Image(str(LOGO), width=1.25 * inch, height=1.25 * inch)
    logo.hAlign = "CENTER"
    story += [logo, Spacer(1, 0.16 * inch), p("LALIGENCE eKYC Project Proposal", "CoverTitle"), p("Secure document verification, liveness, face matching, and face-based payment access", "CoverSub")]
    story.append(table(
        [["Prepared for", "Prepared by", "Date", "Status"], ["Customer / Internal Review", "LALIGENCE eKYC Team", date.today().isoformat(), "Proposal draft"]],
        [1.75 * inch, 1.75 * inch, 1.25 * inch, 1.45 * inch],
    ))
    story += [Spacer(1, 0.15 * inch), callout("Proposal objective", "Build and validate an IAL2-aligned eKYC workflow that verifies identity documents, checks fraud signals, confirms live user presence, matches the selfie to the document portrait, and enables returning face login or Face Pay authorization after enrollment.")]

    story += [p("1. Executive Summary", "H1x"), p("LALIGENCE is a web-first eKYC and secure access platform for identity verification and face-based authorization. The proposed system guides a user through document proofing, active liveness, hand gesture challenge, selfie capture, passive liveness, face matching, and final decisioning. After successful verification, the verified profile can be bound to one active Face ID for future login or payment authorization."), p("The current target is NIST IAL2-aligned readiness rather than a claim of formal certification.")]

    story += [p("2. Project Goals", "H1x"), bullets([
        "Provide a guided verification flow for passport and Lao ID card evidence.",
        "Detect edited portraits, edited dates, visual/MRZ mismatch, non-document upload, and poor-quality captures.",
        "Use active liveness and hand gestures to reduce static photo and replay attacks.",
        "Use passive liveness and face matching to compare selfie with document portrait.",
        "Store only verification results, verified profile attributes, and one active face template per user.",
        "Support returning face login and Face Pay transfer authorization for verified users.",
    ])]

    story += [p("3. Proposed Solution", "H1x"), p("The solution contains a React web app and Python backend. The frontend manages capture, user guidance, step gating, and status display. The backend performs document analysis, OCR/MRZ extraction, fraud scoring, liveness analysis, face matching, profile storage, and face-login matching.")]
    story.append(table(
        [["Layer", "Role", "Key functions"], ["Frontend", "User experience and capture", "Document upload/camera, liveness, gesture UI, selfie, face login, payment authorization"], ["Backend", "Verification intelligence", "OCR, fraud scoring, face matching, anti-spoof checks, profile/session APIs"], ["Database", "Verification and profile records", "One user ID to one active Face ID; one passport number to one verified profile"], ["Models", "Local/open-source AI", "Face detection/recognition, anti-spoofing, OCR/MRZ, document fraud checks"]],
        [1.2 * inch, 1.7 * inch, 3.5 * inch],
    ))

    story += [p("4. End-to-End Workflow", "H1x"), numbers([
        "New user starts signup and receives or enters a user ID.",
        "User uploads or captures passport/Lao ID evidence.",
        "System checks document quality, OCR/MRZ, expiry, and fraud signals.",
        "User performs active face liveness challenges.",
        "User completes hand gesture challenges inside a moving target circle.",
        "User captures selfie for passive liveness and face matching.",
        "System returns final decision, scores, reason codes, and OCR summary.",
        "Accepted user can enroll Face ID for future login and Face Pay authorization.",
    ])]

    story += [PageBreak(), p("5. Usage Guide With Screenshots", "H1x")]
    shots = [
        ("Start Page", "01-start-page.png", "Landing screen with Face Pay transfer, new user signup, face login, and capability cards."),
        ("New User Signup", "02-new-user-signup.png", "New users start verification with a generated or entered user ID."),
        ("Document Proofing", "03-document-proofing.png", "The user uploads or captures passport/Lao ID evidence and sees document quality, fraud risk, and OCR results."),
        ("Active Face Liveness", "04-active-liveness.png", "The user performs live camera actions such as blink, head movement, and mouth opening."),
        ("Hand Gesture Challenge", "05-gesture-challenge.png", "The user performs requested hand gestures in a moving target area."),
        ("Selfie Face Match", "06-selfie-face-match.png", "The user captures a selfie for passive liveness and face matching."),
        ("Result Decision", "07-result-decision.png", "The final result shows decision, OCR, biometric scores, reason codes, and Face ID enrollment."),
        ("Face Login", "08-face-login.png", "Returning verified users can use live face login instead of repeating full onboarding."),
        ("Face Pay Transfer", "09-face-pay-transfer.png", "Payment-style authorization requires verified face scan before transfer approval."),
    ]
    for idx, shot in enumerate(shots):
        story.append(screenshot(*shot))
        if idx in {1, 3, 5, 7}:
            story.append(PageBreak())

    story += [PageBreak(), p("6. Security and Fraud Detection Scope", "H1x")]
    story.append(table(
        [["Control area", "Examples covered", "Expected behavior"], ["Document fraud", "Edited portrait, edited expiry, text overlay, fake template, non-document upload", "Reject or route to manual review with reason codes"], ["Document validity", "Expiry, MRZ checksum, OCR/MRZ consistency, document number", "Reject invalid, expired, or inconsistent evidence"], ["Active liveness", "Blink, mouth open, head turn, screen replay attempts", "Pass only when correct live human action is detected"], ["Gesture challenge", "Random moving target with simple hand signs", "Pass only when correct gesture is detected inside target"], ["Passive liveness", "Paper photo, phone screen, laptop screen, multiple faces", "Reject spoof or replay risk"], ["Face matching", "Same person vs impostor selfie", "Accept above threshold; reject low-match or multiple-face cases"]],
        [1.55 * inch, 2.65 * inch, 2.2 * inch],
    ))
    story += [p("7. NIST IAL2 Alignment", "H1x"), p("The app is intended to support NIST SP 800-63A-4 IAL2-aligned identity proofing. It supports evidence collection, attribute extraction, evidence validation, biometric ownership verification, liveness checks, workflow gating, and audit-style reason codes."), callout("Compliance note", "A formal IAL2 claim requires source validation, privacy notices, retention, deletion, audit logging, notification of proofing, operating procedures, and security controls.")]
    story += [p("8. Implementation Plan", "H1x")]
    story.append(table(
        [["Phase", "Deliverables", "Success criteria"], ["1. Web pilot", "Frontend and backend demo, document proofing, liveness, selfie, result page", "Colleagues complete web end-to-end tests"], ["2. Model tuning", "Dataset tests for document fraud, face match, passive liveness, active liveness", "Measured FAR/FRR and tuned thresholds"], ["3. Profile and payment", "Face ID enrollment, face login, Face Pay transfer authorization", "One active Face ID per user and payment scan works"], ["4. Compliance readiness", "IAL2 test evidence, audit logs, privacy/retention docs, security controls", "Readiness package prepared for customer review"], ["5. Production hardening", "Cloud deployment, database, monitoring, rate limiting, backup", "Stable multi-user testing with acceptable latency"]],
        [1.5 * inch, 2.75 * inch, 2.15 * inch],
    ))
    story += [p("9. Recommendation", "H1x"), p("Proceed with a controlled pilot for internal users and customer demonstration. Use the prepared NIST IAL2 test matrix to measure accuracy, spoof rejection, document fraud rejection, and usability before expanding to production or regulated payment use cases.")]

    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
    print(PDF_PATH)


if __name__ == "__main__":
    build()
