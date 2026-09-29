from __future__ import annotations

from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch, mm
from reportlab.platypus import (
    Flowable,
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


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "guidebook" / "LALIGENCE_eKYC_Guidebook.pdf"
LOGO = ROOT / "frontend" / "src" / "assets" / "logo.png"

PAGE_WIDTH, PAGE_HEIGHT = A4

NAVY = colors.HexColor("#081632")
NAVY_2 = colors.HexColor("#10255a")
GOLD = colors.HexColor("#e7bf35")
GOLD_DARK = colors.HexColor("#c99b18")
INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#66728a")
LIGHT = colors.HexColor("#f5f7fb")
LINE = colors.HexColor("#d9e1ef")
GREEN = colors.HexColor("#197a58")
RED = colors.HexColor("#b42318")
WHITE = colors.white


def styles():
    base = getSampleStyleSheet()
    base.add(
        ParagraphStyle(
            name="CoverTitle",
            fontName="Helvetica-Bold",
            fontSize=34,
            leading=39,
            textColor=NAVY,
            spaceAfter=12,
        )
    )
    base.add(
        ParagraphStyle(
            name="CoverSub",
            fontName="Helvetica",
            fontSize=12.5,
            leading=18,
            textColor=MUTED,
            spaceAfter=12,
        )
    )
    base.add(
        ParagraphStyle(
            name="Eyebrow",
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=GOLD_DARK,
            uppercase=True,
            spaceAfter=7,
        )
    )
    base.add(
        ParagraphStyle(
            name="H1x",
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=27,
            textColor=NAVY,
            spaceAfter=12,
        )
    )
    base.add(
        ParagraphStyle(
            name="H2x",
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=18,
            textColor=NAVY,
            spaceBefore=8,
            spaceAfter=7,
        )
    )
    base.add(
        ParagraphStyle(
            name="Bodyx",
            fontName="Helvetica",
            fontSize=9.6,
            leading=14.2,
            textColor=INK,
            spaceAfter=7,
        )
    )
    base.add(
        ParagraphStyle(
            name="Smallx",
            fontName="Helvetica",
            fontSize=8.2,
            leading=11.2,
            textColor=MUTED,
        )
    )
    base.add(
        ParagraphStyle(
            name="CardTitle",
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=12,
            textColor=NAVY,
            spaceAfter=4,
        )
    )
    base.add(
        ParagraphStyle(
            name="WhiteTitle",
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=18,
            textColor=WHITE,
        )
    )
    base.add(
        ParagraphStyle(
            name="WhiteBody",
            fontName="Helvetica",
            fontSize=9.2,
            leading=13,
            textColor=colors.HexColor("#dce6fb"),
        )
    )
    base.add(
        ParagraphStyle(
            name="CenterSmall",
            fontName="Helvetica-Bold",
            fontSize=8.2,
            leading=10,
            textColor=NAVY,
            alignment=TA_CENTER,
        )
    )
    base.add(
        ParagraphStyle(
            name="StepText",
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=10.5,
            textColor=NAVY,
            alignment=TA_CENTER,
        )
    )
    return base


S = styles()


def p(text: str, style: str = "Bodyx") -> Paragraph:
    return Paragraph(text, S[style])


def bullets(items: list[str], level: int = 0) -> ListFlowable:
    left = 13 + (level * 8)
    return ListFlowable(
        [ListItem(p(item), leftIndent=left, bulletColor=GOLD_DARK) for item in items],
        bulletType="bullet",
        start="circle",
        leftIndent=left,
        bulletFontName="Helvetica-Bold",
        bulletFontSize=5.5,
        bulletColor=GOLD_DARK,
    )


def title_block(kicker: str, title: str, body: str | None = None):
    flow = [p(kicker.upper(), "Eyebrow"), p(title, "H1x")]
    if body:
        flow.append(p(body))
    return flow


def two_col(left, right, widths=(0.48, 0.52)):
    usable = PAGE_WIDTH - 38 * mm
    table = Table([[left, right]], colWidths=[usable * widths[0], usable * widths[1]])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 14),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def card(title: str, body: str, tone: str = "light"):
    bg = WHITE if tone == "white" else LIGHT
    border = LINE
    return Table(
        [[p(title, "CardTitle")], [p(body, "Smallx")]],
        colWidths=[(PAGE_WIDTH - 38 * mm - 10) / 2],
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), bg),
                ("BOX", (0, 0), (-1, -1), 0.8, border),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ]
        ),
    )


class CoverHero(Flowable):
    def __init__(self, width: float, height: float):
        super().__init__()
        self.width = width
        self.height = height

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(NAVY)
        c.roundRect(0, 0, self.width, self.height, 18, fill=1, stroke=0)
        c.setStrokeColor(GOLD)
        c.setLineWidth(1.4)
        c.roundRect(7, 7, self.width - 14, self.height - 14, 15, fill=0, stroke=1)

        # Abstract verification scene.
        x = self.width * 0.51
        y = self.height * 0.22
        c.setFillColor(colors.HexColor("#f8fafc"))
        c.roundRect(x, y, self.width * 0.36, self.height * 0.46, 14, fill=1, stroke=0)
        c.setStrokeColor(colors.HexColor("#cbd5e1"))
        c.setLineWidth(1)
        c.roundRect(x, y, self.width * 0.36, self.height * 0.46, 14, fill=0, stroke=1)
        c.setFillColor(colors.HexColor("#d8e4f1"))
        c.roundRect(x + 18, y + 58, 48, 68, 6, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#d09a74"))
        c.circle(x + 42, y + 102, 14, fill=1, stroke=0)
        c.setFillColor(NAVY_2)
        c.rect(x + 31, y + 58, 22, 34, fill=1, stroke=0)
        c.setFillColor(GOLD)
        for i in range(19):
            c.rect(x + 18 + i * 7.2, y + 20, 3.8, 26, fill=1, stroke=0)
        c.setStrokeColor(GOLD)
        c.setLineWidth(2)
        c.circle(x + 185, y + 116, 46, fill=0, stroke=1)
        c.setFillColor(NAVY_2)
        c.roundRect(x + 148, y + 72, 84, 110, 8, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#d09a74"))
        c.ellipse(x + 177, y + 110, x + 203, y + 154, fill=1, stroke=0)
        c.setStrokeColor(GOLD)
        c.setLineWidth(1.6)
        c.circle(x + 190, y + 132, 34, fill=0, stroke=1)
        c.setFillColor(GREEN)
        c.roundRect(x + 168, y + 91, 44, 7, 3, fill=1, stroke=0)

        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 13)
        c.drawString(34, self.height - 54, "LALIGENCE")
        c.setFillColor(GOLD)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(34, self.height - 70, "SECURE IDENTITY VERIFICATION")
        c.restoreState()


class WorkflowDiagram(Flowable):
    def __init__(self, width: float, height: float = 222):
        super().__init__()
        self.width = width
        self.height = height

    def draw(self):
        c = self.canv
        c.saveState()
        steps = [
            ("1", "Start", "New signup or face login"),
            ("2", "Passport", "Upload or camera capture"),
            ("3", "Document AI", "MRZ, OCR, quality, fraud"),
            ("4", "Face liveness", "Blink, turn, mouth action"),
            ("5", "Gesture", "3 random hand prompts"),
            ("6", "Selfie", "Face match and passive PAD"),
            ("7", "Decision", "Pass, reject, or pending"),
            ("8", "Enroll", "Store Face ID profile"),
        ]
        cols = 4
        box_w = (self.width - 30) / cols
        box_h = 70
        for i, (num, title, sub) in enumerate(steps):
            row = i // cols
            col = i % cols
            x = col * box_w + col * 10
            y = self.height - (row + 1) * box_h - row * 38
            c.setFillColor(WHITE)
            c.roundRect(x, y, box_w, box_h, 9, fill=1, stroke=0)
            c.setStrokeColor(LINE)
            c.setLineWidth(0.9)
            c.roundRect(x, y, box_w, box_h, 9, fill=0, stroke=1)
            c.setFillColor(GOLD)
            c.circle(x + 20, y + box_h - 22, 11, fill=1, stroke=0)
            c.setFillColor(NAVY)
            c.setFont("Helvetica-Bold", 9)
            c.drawCentredString(x + 20, y + box_h - 25, num)
            c.setFont("Helvetica-Bold", 9.5)
            c.drawString(x + 38, y + box_h - 22, title)
            c.setFillColor(MUTED)
            c.setFont("Helvetica", 7.6)
            for j, line in enumerate(wrap(sub, 24)[:2]):
                c.drawString(x + 12, y + 22 - j * 10, line)
            if i not in (3, 7):
                if i == 3:
                    pass
                else:
                    if col < cols - 1:
                        c.setStrokeColor(GOLD_DARK)
                        c.setLineWidth(1.2)
                        arrow(c, x + box_w + 2, y + 35, x + box_w + 9, y + 35)
            if i == 3:
                c.setStrokeColor(GOLD_DARK)
                c.setLineWidth(1.2)
                arrow(c, x + box_w / 2, y - 8, 13, y - 8)
        c.restoreState()


class ArchitectureDiagram(Flowable):
    def __init__(self, width: float, height: float = 230):
        super().__init__()
        self.width = width
        self.height = height

    def draw(self):
        c = self.canv
        c.saveState()
        lanes = [
            ("Frontend", "React/Vite web app, camera capture, step guardrails, branded UI"),
            ("Backend API", "FastAPI sessions, uploads, challenge validation, face enrollment/login"),
            ("AI Services", "Passport fraud analyzer, OCR/MRZ, YuNet/SFace, ONNX passive PAD"),
            ("Storage", "PostgreSQL in deployment, SQLite fallback locally, result/profile metadata"),
            ("SDKs", "TypeScript and Flutter clients call the same backend contract"),
        ]
        box_h = 34
        gap = 12
        for i, (name, desc) in enumerate(lanes):
            y = self.height - (i + 1) * box_h - i * gap
            c.setFillColor(WHITE)
            c.roundRect(0, y, self.width, box_h, 7, fill=1, stroke=0)
            c.setStrokeColor(LINE)
            c.roundRect(0, y, self.width, box_h, 7, fill=0, stroke=1)
            c.setFillColor(NAVY)
            c.setFont("Helvetica-Bold", 9)
            c.drawString(12, y + 20, name)
            c.setFillColor(MUTED)
            c.setFont("Helvetica", 7.5)
            c.drawString(112, y + 20, desc)
            if i < len(lanes) - 1:
                c.setStrokeColor(GOLD_DARK)
                c.setLineWidth(1.2)
                arrow(c, self.width / 2, y - 2, self.width / 2, y - gap + 2)
        c.restoreState()


def wrap(text: str, chars: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 <= chars:
            current = f"{current} {word}".strip()
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def arrow(c, x1, y1, x2, y2):
    c.line(x1, y1, x2, y2)
    if abs(x2 - x1) >= abs(y2 - y1):
        sign = 1 if x2 >= x1 else -1
        c.line(x2, y2, x2 - sign * 4, y2 + 3)
        c.line(x2, y2, x2 - sign * 4, y2 - 3)
    else:
        sign = 1 if y2 >= y1 else -1
        c.line(x2, y2, x2 - 3, y2 - sign * 4)
        c.line(x2, y2, x2 + 3, y2 - sign * 4)


def table(data, widths, header=True):
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    commands = [
        ("BOX", (0, 0), (-1, -1), 0.8, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.45, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]
    if header:
        commands.extend(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3fb")),
                ("LINEBELOW", (0, 0), (-1, 0), 1.0, NAVY),
            ]
        )
    for r in range(1, len(data)):
        if r % 2 == 0:
            commands.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#fbfcff")))
    t.setStyle(TableStyle(commands))
    return t


def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(doc.leftMargin, PAGE_HEIGHT - 18 * mm, PAGE_WIDTH - doc.rightMargin, PAGE_HEIGHT - 18 * mm)
    canvas.setFillColor(NAVY)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawString(doc.leftMargin, PAGE_HEIGHT - 14 * mm, "LALIGENCE eKYC Guidebook")
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawRightString(PAGE_WIDTH - doc.rightMargin, 12 * mm, f"Page {doc.page}")
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(1.1)
    canvas.line(doc.leftMargin, 15 * mm, doc.leftMargin + 32 * mm, 15 * mm)
    canvas.restoreState()


def build():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=19 * mm,
        rightMargin=19 * mm,
        topMargin=23 * mm,
        bottomMargin=20 * mm,
        title="LALIGENCE eKYC Guidebook",
        author="LALIGENCE",
    )
    story = []

    # Cover
    story.append(CoverHero(PAGE_WIDTH - 38 * mm, 205))
    story.append(Spacer(1, 18))
    logo = Image(str(LOGO), width=44 * mm, height=39 * mm)
    story.append(
        two_col(
            [logo, Spacer(1, 12), p("Internal guidebook", "Eyebrow"), p("Passport eKYC with liveness, fraud checks, and Face ID login", "CoverTitle")],
            [
                p(
                    "A start-to-finish guide for colleagues testing and explaining the LALIGENCE eKYC prototype. "
                    "It covers the user workflow, the backend checks, Face ID enrollment, payment/login use cases, model training, datasets, and deployment responsibilities.",
                    "CoverSub",
                ),
                Spacer(1, 10),
                table(
                    [
                        [p("Audience", "CenterSmall"), p("Product, engineering, QA, risk, and demo reviewers", "Smallx")],
                        [p("Version", "CenterSmall"), p(f"Guide generated {date.today().isoformat()}", "Smallx")],
                        [p("Important", "CenterSmall"), p("Use sample or redacted identity documents only in public demos.", "Smallx")],
                    ],
                    [80, 230],
                    header=False,
                ),
            ],
            widths=(0.47, 0.53),
        )
    )
    story.append(PageBreak())

    # Overview
    story.extend(
        title_block(
            "1. Product overview",
            "What the system does",
            "LALIGENCE is a web-first, mobile-ready eKYC prototype for passport proofing. It guides a user through document capture, active liveness, hand gesture challenge, selfie face match, passive liveness, and a final risk decision. After a successful verification, the system can enroll a returning-user Face ID profile for future login or payment confirmation.",
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        two_col(
            [
                p("Core promise", "H2x"),
                bullets(
                    [
                        "Verify passport evidence with OCR, MRZ checks, quality checks, and fraud risk signals.",
                        "Require active human actions before accepting face liveness.",
                        "Require three randomized hand gestures inside a moving challenge area.",
                        "Compare the selfie against the passport portrait and run passive anti-spoofing.",
                        "Store only verification results, verified profile fields, and biometric templates for enrolled users.",
                    ]
                ),
            ],
            [
                p("What this prototype is not yet", "H2x"),
                bullets(
                    [
                        "It is NIST IAL2-aligned as a workflow, not a certified identity proofing service.",
                        "It is not production-ready without stronger privacy, audit, retention, encryption, and admin access controls.",
                        "It does not train models inside the live product. Training happens offline, then exported models are plugged into backend adapters.",
                    ]
                ),
            ],
        )
    )
    story.append(Spacer(1, 14))
    story.append(p("System map", "H2x"))
    story.append(ArchitectureDiagram(PAGE_WIDTH - 38 * mm))
    story.append(PageBreak())

    # Workflow
    story.extend(
        title_block(
            "2. End-to-end workflow",
            "From first signup to verified Face ID",
            "The user journey is intentionally strict: each step unlocks only after the previous evidence passes. A rejected passport blocks liveness; failed active liveness blocks gesture and selfie; failed selfie blocks enrollment.",
        )
    )
    story.append(WorkflowDiagram(PAGE_WIDTH - 38 * mm))
    story.append(Spacer(1, 8))
    story.append(
        table(
            [
                [p("Step", "CenterSmall"), p("User action", "CenterSmall"), p("Backend decision", "CenterSmall")],
                [p("1", "CenterSmall"), p("New user enters user_id or returning user chooses Face Pay login.", "Smallx"), p("Creates a verification session or starts face-login matching.", "Smallx")],
                [p("2", "CenterSmall"), p("Uploads/captures passport.", "Smallx"), p("Checks file type, size, document quality, MRZ/OCR, fraud, and passport portrait face extraction.", "Smallx")],
                [p("3", "CenterSmall"), p("Performs randomized face movement prompts.", "Smallx"), p("Backend verifies captured frame has one live-looking face and no high passive replay risk.", "Smallx")],
                [p("4", "CenterSmall"), p("Performs three random hand gestures inside the circle.", "Smallx"), p("Marks gesture challenge complete only after required prompts pass.", "Smallx")],
                [p("5", "CenterSmall"), p("Captures selfie.", "Smallx"), p("Runs selfie quality, passive liveness, face extraction, and SFace match against passport portrait.", "Smallx")],
                [p("6", "CenterSmall"), p("Reviews result.", "Smallx"), p("Decision is passed, rejected, or pending with reason codes.", "Smallx")],
                [p("7", "CenterSmall"), p("Enrolls Face ID after pass.", "Smallx"), p("Stores one active face_id per user_id and one verified profile per passport number.", "Smallx")],
            ],
            [35, 206, 250],
        )
    )
    story.append(PageBreak())

    # Passport
    story.extend(
        title_block(
            "3. Passport upload",
            "What happens when a document is uploaded",
            "The passport step is the gatekeeper. It must confirm that the evidence looks like a passport, contains readable passport data, has a usable portrait, and does not show strong signs of editing, screen replay, or poor capture quality.",
        )
    )
    story.append(
        two_col(
            [
                p("Checks performed", "H2x"),
                bullets(
                    [
                        "Content type and maximum file size.",
                        "Image quality: resolution, brightness, contrast, blur, sharpness, and glare.",
                        "Document likeness: rectangular document structure and passport-like layout cues.",
                        "OCR/MRZ: TD3 MRZ extraction, field parsing, and check-digit validation.",
                        "Fraud risk: recapture artifacts, compression anomalies, text overlay/editing, crop replacement, and portrait-substitution cues.",
                        "Passport portrait face detection and in-memory embedding extraction for later selfie comparison.",
                    ]
                ),
            ],
            [
                p("Important rejection examples", "H2x"),
                bullets(
                    [
                        "Non-document image, such as a random photo or object.",
                        "Unreadable or invalid MRZ.",
                        "Expired passport once expiry is extracted.",
                        "Severe blur, glare, or cropped evidence.",
                        "High document fraud risk or high tamper risk.",
                        "No usable face found in the passport portrait area.",
                    ]
                ),
            ],
        )
    )
    story.append(Spacer(1, 10))
    story.append(
        table(
            [
                [p("Output", "CenterSmall"), p("Meaning", "CenterSmall")],
                [p("OCR fields", "Smallx"), p("Name, passport number, nationality, birth date, expiry, MRZ validity, and raw extracted fields.", "Smallx")],
                [p("Scores", "Smallx"), p("Image quality, document likeness, recapture risk, tamper risk, fraud risk.", "Smallx")],
                [p("Signals", "Smallx"), p("Explainable reason codes such as MRZ_NOT_READ, BLUR_DETECTED, DOCUMENT_FACE_NOT_FOUND, or DOCUMENT_FRAUD_RISK_HIGH.", "Smallx")],
                [p("Session embedding", "Smallx"), p("The passport portrait template is kept only in the in-memory verification session for selfie matching.", "Smallx")],
            ],
            [105, 386],
        )
    )
    story.append(PageBreak())

    # Liveness
    story.extend(
        title_block(
            "4. Liveness and gesture challenge",
            "How the system reduces replay risk",
            "Active liveness and hand gestures make the flow harder to pass with only a static photo. The current web test version focuses on correct action detection plus backend evidence validation. Stronger production replay defense requires calibrated PAD data and challenge-response timing controls.",
        )
    )
    story.append(
        two_col(
            [
                p("Active face liveness", "H2x"),
                bullets(
                    [
                        "The session randomly selects three prompts: turn left, turn right, blink, or open mouth.",
                        "The browser detects movement locally to guide the user.",
                        "The backend receives challenge evidence through /active-liveness.",
                        "The backend checks exactly one usable face and runs passive PAD against the captured frame.",
                    ]
                ),
                Spacer(1, 8),
                card("Replay warning", "Frontend landmark motion alone is not enough. A phone video can mimic blink and head movement, so the backend must inspect captured evidence before accepting a challenge."),
            ],
            [
                p("Hand gesture challenge", "H2x"),
                bullets(
                    [
                        "Three hand prompts are randomly selected from one, two, three, four, five, OK, thumb down, and I love you.",
                        "The challenge circle appears at random positions and requires the hand to be inside it.",
                        "The frontend uses gesture detection for a smooth test experience.",
                        "A production version should store signed challenge evidence or server-verify gesture frames.",
                    ]
                ),
                Spacer(1, 8),
                card("Why random prompts matter", "Random prompts make pre-recorded attacks harder because the attacker must know the action sequence and timing before the session starts."),
            ],
        )
    )
    story.append(PageBreak())

    # Selfie
    story.extend(
        title_block(
            "5. Selfie, face match, and Face ID",
            "How a verified profile is created",
            "The selfie step confirms that the live person matches the passport portrait. A passed verification can then create a profile for returning login and future payment confirmation.",
        )
    )
    story.append(
        table(
            [
                [p("Component", "CenterSmall"), p("Current implementation", "CenterSmall"), p("Why it matters", "CenterSmall")],
                [p("Face detection", "Smallx"), p("OpenCV YuNet ONNX.", "Smallx"), p("Finds the user face in passport, selfie, and login images.", "Smallx")],
                [p("Face matching", "Smallx"), p("OpenCV SFace ONNX embeddings and similarity comparison.", "Smallx"), p("Rejects selfie evidence that does not match the passport portrait.", "Smallx")],
                [p("Passive PAD", "Smallx"), p("facenox/Silent-Face-Anti-Spoofing ONNX plus full-frame screen/phone heuristics.", "Smallx"), p("Catches screen replay, paper/photo attacks, and suspicious display frames.", "Smallx")],
                [p("Enrollment", "Smallx"), p("POST /api/verifications/{session_id}/enroll-face after decision passed.", "Smallx"), p("Creates one active face_id per user_id and one verified profile per passport number.", "Smallx")],
                [p("Face login", "Smallx"), p("POST /api/face-login with fresh live selfie.", "Smallx"), p("Matches returning users and returns verified profile fields for login or payment.", "Smallx")],
            ],
            [86, 214, 191],
        )
    )
    story.append(Spacer(1, 12))
    story.append(
        two_col(
            [
                p("Stored after enrollment", "H2x"),
                bullets(
                    [
                        "face_id, user_id, active flag, verification session ID.",
                        "Full name, first name, last name, age, date of birth, nationality.",
                        "Passport number and passport expiry.",
                        "Face template vector, model metadata, enrollment and last-login timestamps.",
                    ]
                ),
            ],
            [
                p("Not stored by policy", "H2x"),
                bullets(
                    [
                        "Raw passport image.",
                        "Raw selfie image.",
                        "Raw liveness or gesture video.",
                        "Unprotected biometric data for public production use.",
                    ]
                ),
            ],
        )
    )
    story.append(PageBreak())

    # Payment
    story.extend(
        title_block(
            "6. Payment/banking use case",
            "Face Pay transfer flow",
            "The app can act like a banking demo: new users verify once, enroll Face ID, and later authorize transfer actions with a live face check instead of repeating full passport proofing.",
        )
    )
    story.append(
        table(
            [
                [p("Flow", "CenterSmall"), p("Action", "CenterSmall"), p("Security check", "CenterSmall")],
                [p("Signup", "Smallx"), p("User starts as a new customer and enters the app's real user_id.", "Smallx"), p("Full eKYC: passport, liveness, gesture, selfie, final decision.", "Smallx")],
                [p("Enroll", "Smallx"), p("After pass, backend stores a verified Face ID profile.", "Smallx"), p("One user_id to one active face_id; one passport number to one verified profile.", "Smallx")],
                [p("Transfer", "Smallx"), p("Returning user taps Face Pay transfer.", "Smallx"), p("Backend checks live face, passive PAD, and template match.", "Smallx")],
                [p("Approve", "Smallx"), p("If matched, app can display verified profile and continue payment authorization.", "Smallx"), p("Production should add amount limits, device trust, audit logs, and step-up auth for high-risk payments.", "Smallx")],
            ],
            [80, 214, 197],
        )
    )
    story.append(Spacer(1, 12))
    story.append(
        card(
            "Production banking note",
            "Face login is a biometric authentication signal, not a complete payment authorization system by itself. For real banking use, combine it with account authentication, device binding, transaction risk scoring, consent, audit logs, and regulatory review.",
        )
    )
    story.append(PageBreak())

    # Training
    story.extend(
        title_block(
            "7. How the AI is trained and tested",
            "Offline training, online inference",
            "The live backend should not train models on user uploads. Training and calibration happen offline with consented, labeled data. The trained model is exported to ONNX or another runtime format, then plugged into backend adapters for inference.",
        )
    )
    story.append(
        table(
            [
                [p("Model area", "CenterSmall"), p("Classes to collect", "CenterSmall"), p("Key metrics", "CenterSmall")],
                [p("Passport fraud", "Smallx"), p("Genuine passport, crop/face replacement, text/field edit, text overlay, expired, missing fields, blur/glare, screen/print recapture, non-document.", "Smallx"), p("False accept rate, false reject rate, precision/recall by fraud class, MRZ read rate.", "Smallx")],
                [p("Passive face PAD", "Smallx"), p("Live face, screen replay, phone display, printed photo, paper/cardboard mask, low-light live, glasses live.", "Smallx"), p("APCER, BPCER, ACER, spoof false accept, live false reject.", "Smallx")],
                [p("Active liveness", "Smallx"), p("Correct human actions, wrong actions, still image, replayed video, multiple faces, poor lighting.", "Smallx"), p("Challenge pass rate, replay failure rate, action confusion matrix.", "Smallx")],
                [p("Gesture", "Smallx"), p("Each supported hand gesture, wrong gesture, hand outside circle, low light, background hands.", "Smallx"), p("Gesture accuracy, per-class recall, false pass for wrong prompt.", "Smallx")],
                [p("Face match", "Smallx"), p("Same-person passport/selfie pairs, different-person pairs, age/lighting variation, document photo variation.", "Smallx"), p("FAR, FRR, ROC/AUC, threshold at acceptable risk.", "Smallx")],
            ],
            [87, 254, 150],
        )
    )
    story.append(Spacer(1, 10))
    story.append(
        two_col(
            [
                p("Recommended training process", "H2x"),
                bullets(
                    [
                        "Define labels and reject reasons before collecting data.",
                        "Split by person/document, not randomly by image, to avoid leakage.",
                        "Train on train set, tune thresholds on validation set, report only test-set metrics.",
                        "Export model to ONNX and wrap it in a backend service adapter.",
                        "Calibrate thresholds for the business risk: low false accept for security, controlled false reject for usability.",
                    ]
                ),
            ],
            [
                p("Current local test data", "H2x"),
                bullets(
                    [
                        "IDNet-style generated genuine and fraud examples under test_dataset.",
                        "1,200 synthetic hard passport-scene images for upload stress testing.",
                        "Selfie spoof installer for screen, paper, and larger AxonData frame samples.",
                        "MIDV-2020 support after the licensed dataset is downloaded locally.",
                    ]
                ),
            ],
        )
    )
    story.append(PageBreak())

    # Testing
    story.extend(
        title_block(
            "8. How QA should test it",
            "Test scripts and expected outputs",
            "Testing should measure both security and usability. A good detector must reject attacks, but it must also avoid rejecting too many real users under normal phone and laptop conditions.",
        )
    )
    commands = [
        ["Backend compile", "PYTHONPATH=backend .venv/bin/python -m compileall backend/app"],
        ["Frontend build", "npm run build"],
        ["Document fraud benchmark", "PYTHONPATH=backend .venv/bin/python backend/scripts/evaluate_document_fraud.py --dataset test_dataset"],
        ["Upload route benchmark", "PYTHONPATH=backend .venv/bin/python backend/scripts/evaluate_document_upload.py --dataset test_dataset --only-folder genuine_synthetic_us_passports_hard"],
        ["Selfie spoof benchmark", "PYTHONPATH=backend .venv/bin/python backend/scripts/evaluate_selfie_spoof.py --dataset test_dataset/selfie_spoof"],
        ["List demo profiles", "curl http://localhost:8000/api/profiles | python -m json.tool"],
    ]
    story.append(
        table(
            [[p("Test", "CenterSmall"), p("Command", "CenterSmall")]]
            + [[p(a, "Smallx"), p(b, "Smallx")] for a, b in commands],
            [120, 371],
        )
    )
    story.append(Spacer(1, 12))
    story.append(
        two_col(
            [
                p("Security tests", "H2x"),
                bullets(
                    [
                        "Upload edited passport photo and confirm rejection.",
                        "Upload non-document image and confirm rejection.",
                        "Try phone screen replay for active liveness and selfie.",
                        "Try a different person's selfie against a passport.",
                        "Try multiple faces in selfie/login frame.",
                    ]
                ),
            ],
            [
                p("Usability tests", "H2x"),
                bullets(
                    [
                        "Test real passport in daylight, low light, and mild glare.",
                        "Test live selfie with and without glasses.",
                        "Test mobile camera on same network and public HTTPS URL.",
                        "Check mobile layout for start page, document, liveness, gesture, selfie, and result.",
                        "Record false rejects with reason codes and sample conditions.",
                    ]
                ),
            ],
        )
    )
    story.append(PageBreak())

    # Deployment
    story.extend(
        title_block(
            "9. Deployment and operations",
            "How colleagues can test together",
            "The preferred company demo setup is a DigitalOcean Singapore backend with PostgreSQL and Caddy HTTPS, plus a Vercel frontend. This avoids Render sleep and keeps the API closer to Laos and Southeast Asia testers.",
        )
    )
    story.append(
        table(
            [
                [p("Layer", "CenterSmall"), p("Recommended setup", "CenterSmall"), p("Why", "CenterSmall")],
                [p("Backend", "Smallx"), p("DigitalOcean Droplet, Singapore, Docker Compose.", "Smallx"), p("Stable machine, no free-tier sleep, closer region.", "Smallx")],
                [p("Database", "Smallx"), p("PostgreSQL in Docker for demo or managed PostgreSQL for production.", "Smallx"), p("Stores verified profiles and Face ID templates.", "Smallx")],
                [p("TLS/proxy", "Smallx"), p("Caddy with API domain.", "Smallx"), p("Browsers and phones require HTTPS for camera and secure uploads.", "Smallx")],
                [p("Frontend", "Smallx"), p("Vercel static Vite deployment.", "Smallx"), p("Fast static hosting and easy env config.", "Smallx")],
                [p("Mobile SDK", "Smallx"), p("TypeScript SDK and Flutter package call the same API.", "Smallx"), p("Mobile UI stays thin; backend owns risk decisions.", "Smallx")],
            ],
            [83, 221, 187],
        )
    )
    story.append(Spacer(1, 12))
    story.append(
        card(
            "Environment settings to confirm",
            "Set VITE_API_BASE_URL on the frontend. Set DATABASE_URL, LALIGENCE_CORS_ORIGINS, upload size limits, rate limit, and Face ID thresholds on the backend. Keep CORS explicit for hosted demos.",
        )
    )
    story.append(PageBreak())

    # Production checklist
    story.extend(
        title_block(
            "10. Production readiness checklist",
            "What must be added before real customers",
            "The prototype is useful for internal demos and model evaluation. Production eKYC requires stronger compliance, data protection, observability, and operational controls.",
        )
    )
    story.append(
        two_col(
            [
                p("Security and privacy", "H2x"),
                bullets(
                    [
                        "Encrypt biometric templates at rest.",
                        "Add authentication and authorization to profile/admin endpoints.",
                        "Add consent capture and clear retention/deletion policy.",
                        "Add audit logs for verification, enrollment, login, and deletion.",
                        "Protect secrets and database backups.",
                        "Run threat modeling for spoofing, replay, account takeover, and insider access.",
                    ]
                ),
                Spacer(1, 10),
                p("Model governance", "H2x"),
                bullets(
                    [
                        "Version every model and threshold.",
                        "Keep benchmark datasets separate from training data.",
                        "Track false accepts and false rejects by device and lighting condition.",
                        "Add manual review lane for borderline cases.",
                    ]
                ),
            ],
            [
                p("Compliance and operations", "H2x"),
                bullets(
                    [
                        "Review NIST IAL2 requirements formally; do not claim certification without assessment.",
                        "Add monitoring, uptime alerts, and health checks.",
                        "Add automated PostgreSQL backups and restore drills.",
                        "Add load testing for upload and face-login endpoints.",
                        "Create incident response procedure for biometric and identity data exposure.",
                        "Document tester guidance: use sample or redacted documents only.",
                    ]
                ),
                Spacer(1, 10),
                p("Key message for colleagues", "H2x"),
                card(
                    "How to explain the system",
                    "LALIGENCE verifies passport evidence, proves the person is live, matches the selfie to the document portrait, gives an explainable decision, and can enroll a Face ID profile for later login or Face Pay transfer.",
                ),
            ],
        )
    )

    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)


if __name__ == "__main__":
    build()
    print(OUT)
