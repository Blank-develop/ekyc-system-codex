from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "project-overview.pdf"
LOGO = ROOT / "frontend" / "src" / "assets" / "logo.png"

NAVY = colors.HexColor("#071736")
BLUE = colors.HexColor("#173a7a")
GOLD = colors.HexColor("#e4bd24")
GREEN = colors.HexColor("#16805d")
MUTED = colors.HexColor("#65728b")
LIGHT = colors.HexColor("#f5f8fd")
LINE = colors.HexColor("#d9e2f0")
WHITE = colors.white


def wrap_text(text: str, font: str, size: float, max_width: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if stringWidth(candidate, font, size) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def rounded_rect(c: canvas.Canvas, x: float, y: float, w: float, h: float, fill=WHITE, stroke=LINE, radius=5) -> None:
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1)


def draw_text(c: canvas.Canvas, text: str, x: float, y: float, font="Helvetica", size=9, color=NAVY) -> float:
    c.setFont(font, size)
    c.setFillColor(color)
    c.drawString(x, y, text)
    return y - size * 1.25


def draw_wrapped(c: canvas.Canvas, text: str, x: float, y: float, max_width: float, font="Helvetica", size=8.5, color=MUTED, leading=10.8) -> float:
    c.setFont(font, size)
    c.setFillColor(color)
    for line in wrap_text(text, font, size, max_width):
        c.drawString(x, y, line)
        y -= leading
    return y


def draw_section_title(c: canvas.Canvas, title: str, x: float, y: float) -> float:
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(NAVY)
    c.drawString(x, y, title)
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.2)
    c.line(x, y - 4, x + 28 * mm, y - 4)
    return y - 13


def draw_workflow(c: canvas.Canvas, x: float, y: float, w: float) -> None:
    steps = [
        "Start",
        "Document",
        "Liveness",
        "Gesture",
        "Selfie",
        "Decision",
        "Face ID",
    ]
    gap = 4
    box_w = (w - gap * (len(steps) - 1)) / len(steps)
    box_h = 15
    for index, step in enumerate(steps):
        bx = x + index * (box_w + gap)
        rounded_rect(c, bx, y, box_w, box_h, fill=LIGHT, stroke=LINE, radius=4)
        c.setFont("Helvetica-Bold", 7.2)
        c.setFillColor(NAVY)
        c.drawCentredString(bx + box_w / 2, y + 5.4, step)
        if index < len(steps) - 1:
            c.setStrokeColor(GOLD)
            c.setLineWidth(1.1)
            c.line(bx + box_w, y + box_h / 2, bx + box_w + gap, y + box_h / 2)


def draw_capability_card(c: canvas.Canvas, title: str, body: str, x: float, y: float, w: float, h: float, accent=GOLD) -> None:
    rounded_rect(c, x, y, w, h, fill=WHITE, stroke=LINE, radius=5)
    c.setFillColor(accent)
    c.roundRect(x + 5, y + h - 10, 18, 4, 2, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(NAVY)
    c.drawString(x + 5, y + h - 20, title)
    draw_wrapped(c, body, x + 5, y + h - 31, w - 10, size=7.2, leading=8.5)


def draw_module_list(c: canvas.Canvas, title: str, items: list[tuple[str, str]], x: float, y: float, w: float, h: float) -> None:
    rounded_rect(c, x, y, w, h, fill=WHITE, stroke=LINE, radius=5)
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(NAVY)
    c.drawString(x + 7, y + h - 14, title)
    cursor = y + h - 27
    for name, desc in items:
        c.setFont("Helvetica-Bold", 6.9)
        c.setFillColor(BLUE)
        c.drawString(x + 7, cursor, name)
        cursor -= 7.4
        cursor = draw_wrapped(c, desc, x + 7, cursor, w - 14, size=6.6, leading=7.7)
        cursor -= 2.5


def build_pdf() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    page_w, page_h = landscape(A4)
    c = canvas.Canvas(str(OUTPUT), pagesize=landscape(A4))
    c.setTitle("LALIGENCE eKYC Project Overview")

    margin = 13 * mm
    c.setFillColor(WHITE)
    c.rect(0, 0, page_w, page_h, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.rect(0, page_h - 14, page_w, 14, fill=1, stroke=0)
    c.setFillColor(GOLD)
    c.rect(0, page_h - 17, page_w, 3, fill=1, stroke=0)

    if LOGO.exists():
        rounded_rect(c, margin, page_h - 55, 27 * mm, 29 * mm, fill=WHITE, stroke=LINE, radius=4)
        c.drawImage(str(LOGO), margin + 4, page_h - 51, width=22 * mm, height=22 * mm, preserveAspectRatio=True, mask="auto")

    title_x = margin + 36 * mm
    c.setFont("Helvetica-Bold", 20)
    c.setFillColor(NAVY)
    c.drawString(title_x, page_h - 31, "LALIGENCE eKYC Project Overview")
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(GOLD)
    c.drawString(title_x, page_h - 44, "DOCUMENT PROOFING | LIVENESS | FACE ID | RISK DECISION")

    intro = (
        "A web-first identity verification and face-login prototype for passport/Lao ID onboarding, live user proofing, "
        "selfie face matching, fraud risk decisions, and returning-user Face ID authentication."
    )
    draw_wrapped(c, intro, title_x, page_h - 57, page_w - title_x - margin, size=8.8, leading=10.5)

    left_x = margin
    top_y = page_h - 82
    content_w = page_w - 2 * margin
    draw_section_title(c, "End-to-end workflow", left_x, top_y)
    draw_workflow(c, left_x, top_y - 30, content_w)

    panel_top = top_y - 64
    panel_h = 96 * mm
    gap = 6
    panel_w = (content_w - gap * 2) / 3

    panels = [
        (
            "User Journey",
            GOLD,
            [
                ("Start / New user", "Create a verification session with a generated or supplied user ID."),
                ("Document proofing", "Upload or camera-capture passport/Lao ID evidence."),
                ("Active liveness", "Perform random blink, mouth, and head-movement checks."),
                ("Gesture challenge", "Show 3 random hand gestures inside a moving target circle."),
                ("Selfie match", "Capture a live selfie and compare it to the document portrait."),
                ("Result", "Return pass/reject, reason codes, OCR, risk, and match scores."),
                ("Face ID", "Enroll a verified face for login and Face Pay-style approval."),
            ],
        ),
        (
            "Security Intelligence",
            BLUE,
            [
                ("OCR/MRZ", "Reads passport MRZ and key ID fields; validates expiry and check digits when available."),
                ("Document fraud", "Scores quality, document-likeness, tamper cues, recapture risk, portrait substitution, and printed-copy risk."),
                ("Face recognition", "Uses OpenCV YuNet + SFace for document/selfie embeddings and comparison."),
                ("Passive liveness", "Combines ONNX anti-spoof models with screen, phone, paper, glare, and moire heuristics."),
                ("Step control", "Locks later steps until previous proofing steps pass."),
                ("Auto rejection", "High-risk signals produce explainable reason codes instead of silent failure."),
            ],
        ),
        (
            "Platform & Testing",
            GREEN,
            [
                ("Backend", "Python FastAPI API with local model adapters and configurable thresholds."),
                ("Frontend", "React/Vite camera workflow with branded UX and mobile-aware capture."),
                ("Storage", "SQLite locally and PostgreSQL in deployment through SQLAlchemy."),
                ("SDKs", "Flutter and TypeScript SDKs wrap the same backend API."),
                ("Datasets", "Scripts support document fraud, print-copy, selfie spoof, and camera collection tests."),
                ("Deployment", "Render, DigitalOcean/Caddy/PostgreSQL, Vercel, and Cloudflare tunnel options."),
            ],
        ),
    ]

    for index, (title, accent, rows) in enumerate(panels):
        x = left_x + index * (panel_w + gap)
        y = panel_top - panel_h
        rounded_rect(c, x, y, panel_w, panel_h, fill=WHITE, stroke=LINE, radius=6)
        c.setFillColor(accent)
        c.roundRect(x + 7, y + panel_h - 12, 24, 4, 2, fill=1, stroke=0)
        c.setFont("Helvetica-Bold", 13)
        c.setFillColor(NAVY)
        c.drawString(x + 8, y + panel_h - 28, title)
        cursor = y + panel_h - 47
        for name, desc in rows:
            c.setFillColor(accent)
            c.circle(x + 10, cursor + 2, 1.6, fill=1, stroke=0)
            c.setFont("Helvetica-Bold", 8.1)
            c.setFillColor(BLUE)
            c.drawString(x + 15, cursor, name)
            cursor -= 9
            cursor = draw_wrapped(c, desc, x + 15, cursor, panel_w - 23, size=7.6, leading=8.8)
            cursor -= 5

    footer_y = 16
    rounded_rect(c, margin, footer_y, content_w, 26, fill=LIGHT, stroke=LINE, radius=5)
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(NAVY)
    c.drawString(margin + 7, footer_y + 16, "Data and security note")
    note = (
        "Raw uploads are analyzed in-memory during normal verification. Enrolled profiles store verified fields and face templates. "
        "Production hardening still needs encrypted biometric storage, consent/retention policy, audit logging, protected admin APIs, and larger calibrated validation datasets."
    )
    draw_wrapped(c, note, margin + 7, footer_y + 7, content_w - 14, size=7.1, leading=8)

    c.showPage()
    c.save()


if __name__ == "__main__":
    build_pdf()
    print(OUTPUT)
