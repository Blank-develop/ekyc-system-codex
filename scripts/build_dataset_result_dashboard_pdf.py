from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "test_dataset"
OUTPUT = ROOT / "docs" / "dataset-result-dashboard.pdf"
LOGO = ROOT / "frontend" / "src" / "assets" / "logo.png"
PAGE_SIZE = (960, 540)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".avi"}


@dataclass(frozen=True)
class ModuleSummary:
    name: str
    expected_pass: int
    expected_fail: int
    status: str
    note: str

    @property
    def total(self) -> int:
        return self.expected_pass + self.expected_fail


def count_files(paths: Iterable[Path], extensions: set[str] = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS) -> int:
    total = 0
    for path in paths:
        if not path.exists():
            continue
        total += sum(1 for item in path.rglob("*") if item.is_file() and item.suffix.lower() in extensions)
    return total


def count_images(paths: Iterable[Path]) -> int:
    return count_files(paths, IMAGE_EXTENSIONS)


def count_videos(paths: Iterable[Path]) -> int:
    return count_files(paths, VIDEO_EXTENSIONS)


def folder(name: str) -> Path:
    return DATASET / name


def leaf(parent: str, child: str) -> Path:
    return DATASET / parent / child


def build_summaries() -> list[ModuleSummary]:
    passport_pass = count_images([
        folder("genuine"),
        folder("genuine_synthetic_us_passports_hard"),
        folder("genuine_midv2020_passport"),
    ])
    passport_fail = count_images([
        folder("fraud_crop_replace"),
        folder("fraud_text_or_field_edit"),
        folder("fraud_face_substitution"),
        folder("fraud_expired"),
        folder("fraud_missing_fields"),
        folder("fraud_quality_blur"),
        folder("fraud_text_overlay"),
    ])

    lao_id_pass = count_images([folder("lao_id_card")])

    printed_pass = count_images([
        leaf("document_print_copy", "real_camera_passport"),
        leaf("document_print_copy", "real_camera_lao_id"),
    ])
    printed_fail = count_images([
        leaf("document_print_copy", "fake_printed_passport_on_paper"),
        leaf("document_print_copy", "fake_printed_lao_id_on_paper"),
        leaf("document_print_copy", "fake_photocopy_or_scan"),
        leaf("document_print_copy", "fake_screen_display"),
    ])

    active_pass = count_files([
        leaf("active_liveness", "real_live_face"),
        leaf("active_liveness", "real_live_face_with_glasses"),
        leaf("active_liveness", "real_live_poor_lighting"),
    ])
    active_fail = count_files([
        leaf("active_liveness", "fake_phone_screen_replay"),
        leaf("active_liveness", "fake_tablet_screen_replay"),
        leaf("active_liveness", "fake_laptop_screen_replay"),
        leaf("active_liveness", "fake_video_replay_closeup"),
        leaf("active_liveness", "fake_printed_photo"),
    ])

    gesture_pass = count_files([folder("gesture"), folder("hand_gesture")])
    gesture_fail = 0

    selfie_pass = count_images([
        leaf("selfie_passive_liveness_face_login", "real_live_match"),
        leaf("selfie_spoof", "live_user_provided"),
    ])
    selfie_fail = count_images([
        leaf("selfie_passive_liveness_face_login", "fake_phone_screen_photo"),
        leaf("selfie_passive_liveness_face_login", "fake_tablet_laptop_screen"),
        leaf("selfie_passive_liveness_face_login", "fake_video_replay"),
        leaf("selfie_passive_liveness_face_login", "fake_printed_photo"),
        leaf("selfie_passive_liveness_face_login", "fake_cutout_or_paper_mask"),
        leaf("selfie_passive_liveness_face_login", "multiple_faces"),
        leaf("selfie_passive_liveness_face_login", "no_valid_face"),
        leaf("selfie_spoof", "spoof_mask_cutout"),
        leaf("selfie_spoof", "spoof_print_paper"),
        leaf("selfie_spoof", "spoof_screen_replay"),
        leaf("selfie_spoof", "spoof_unknown"),
    ])

    face_login_pass = count_files([leaf("face_login", "enrolled_real_live")])
    face_login_fail = count_files([
        leaf("face_login", "unknown_real_live"),
        leaf("face_login", "enrolled_screen_replay"),
        leaf("face_login", "unknown_screen_replay"),
        leaf("face_login", "enrolled_printed_photo"),
        leaf("face_login", "multiple_faces"),
        leaf("face_login", "no_valid_face"),
    ])

    return [
        ModuleSummary("Passport upload / fraud", passport_pass, passport_fail, status_for(passport_pass, passport_fail, 100), "Ready for first broad document benchmark; add more rare real fraud."),
        ModuleSummary("Lao ID OCR", lao_id_pass, 0, "Partial", "Detector data exists, but OCR needs real expected-name/expiry labels."),
        ModuleSummary("Printed document copy", printed_pass, printed_fail, status_for(printed_pass, printed_fail, 50), "Too small for accuracy; collect printed and real camera samples."),
        ModuleSummary("Active liveness", active_pass, active_fail, status_for(active_pass, active_fail, 30), "Needs videos or frame bursts for real and replay actions."),
        ModuleSummary("Hand gesture", gesture_pass, gesture_fail, "Needs data", "No usable gesture dataset counted in test_dataset."),
        ModuleSummary("Selfie passive liveness", selfie_pass, selfie_fail, "Partial", "Spoof set is strong; real-live positives are still too small."),
        ModuleSummary("Face login", face_login_pass, face_login_fail, status_for(face_login_pass, face_login_fail, 30), "Needs enrolled identities, unknown users, and replay attempts."),
    ]


def status_for(pass_count: int, fail_count: int, minimum_per_side: int) -> str:
    if pass_count >= minimum_per_side and fail_count >= minimum_per_side:
        return "Ready"
    if pass_count + fail_count > 0:
        return "Partial"
    return "Needs data"


def draw_text(c: canvas.Canvas, text: str, x: float, y: float, size: float, color: colors.Color, font: str = "Helvetica") -> None:
    c.setFillColor(color)
    c.setFont(font, size)
    c.drawString(x, y, text)


def draw_wrapped(c: canvas.Canvas, text: str, x: float, y: float, width: float, size: float, color: colors.Color, leading: float = 12) -> float:
    words = text.split()
    lines: list[str] = []
    current = ""
    c.setFont("Helvetica", size)
    for word in words:
        candidate = f"{current} {word}".strip()
        if c.stringWidth(candidate, "Helvetica", size) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)

    c.setFillColor(color)
    c.setFont("Helvetica", size)
    for line in lines:
        c.drawString(x, y, line)
        y -= leading
    return y


def draw_card(c: canvas.Canvas, x: float, y: float, w: float, h: float, fill: colors.Color = colors.white, stroke: colors.Color = colors.HexColor("#DCE4F2")) -> None:
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.roundRect(x, y, w, h, 8, fill=1, stroke=1)


def draw_kpi(c: canvas.Canvas, x: float, y: float, w: float, h: float, label: str, value: str, accent: colors.Color) -> None:
    draw_card(c, x, y, w, h)
    c.setFillColor(accent)
    c.roundRect(x + 12, y + h - 20, 38, 6, 3, fill=1, stroke=0)
    draw_text(c, label, x + 12, y + h - 34, 8.2, colors.HexColor("#66728A"), "Helvetica-Bold")
    draw_text(c, value, x + 12, y + 12, 21, colors.HexColor("#071227"), "Helvetica-Bold")


def draw_status_pill(c: canvas.Canvas, status: str, x: float, y: float) -> None:
    palette = {
        "Ready": (colors.HexColor("#DEF7EC"), colors.HexColor("#13795B")),
        "Partial": (colors.HexColor("#FFF6D8"), colors.HexColor("#C9A12A")),
        "Needs data": (colors.HexColor("#FFE6E3"), colors.HexColor("#B42318")),
    }
    fill, text = palette[status]
    c.setFillColor(fill)
    c.roundRect(x, y, 68, 18, 7, fill=1, stroke=0)
    draw_text(c, status, x + 8, y + 5, 7.8, text, "Helvetica-Bold")


def build_pdf() -> None:
    summaries = build_summaries()
    image_total = count_images([DATASET])
    video_total = count_videos([DATASET])
    ready_count = sum(1 for item in summaries if item.status == "Ready")
    partial_count = sum(1 for item in summaries if item.status == "Partial")
    needs_count = sum(1 for item in summaries if item.status == "Needs data")
    expected_pass = sum(item.expected_pass for item in summaries)
    expected_fail = sum(item.expected_fail for item in summaries)
    expected_total = expected_pass + expected_fail

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUTPUT), pagesize=PAGE_SIZE)
    w, h = PAGE_SIZE

    navy = colors.HexColor("#071B69")
    navy_dark = colors.HexColor("#020A2A")
    gold = colors.HexColor("#E0B935")
    muted = colors.HexColor("#66728A")
    line = colors.HexColor("#DCE4F2")
    mist = colors.HexColor("#F5F8FF")
    danger = colors.HexColor("#B42318")
    success = colors.HexColor("#13795B")

    c.setFillColor(mist)
    c.rect(0, 0, w, h, fill=1, stroke=0)
    c.setFillColor(navy_dark)
    c.rect(0, h - 54, w, 54, fill=1, stroke=0)
    c.setFillColor(gold)
    c.rect(0, h - 58, w, 4, fill=1, stroke=0)

    if LOGO.exists():
        c.drawImage(ImageReader(str(LOGO)), 34, h - 47, width=62, height=34, preserveAspectRatio=True, mask="auto")
    draw_text(c, "Kyron eKYC Dataset Result Dashboard", 112, h - 31, 21, colors.white, "Helvetica-Bold")
    draw_text(c, "Expected pass/fail readiness snapshot - generated from local test_dataset", 112, h - 46, 8.6, colors.HexColor("#D8E1F3"), "Helvetica")

    draw_kpi(c, 34, h - 132, 122, 66, "Images counted", f"{image_total:,}", navy)
    draw_kpi(c, 166, h - 132, 122, 66, "Videos counted", f"{video_total:,}", gold)
    draw_kpi(c, 298, h - 132, 122, 66, "Ready modules", f"{ready_count}/{len(summaries)}", success)
    draw_kpi(c, 430, h - 132, 122, 66, "Need data", f"{needs_count}", danger)

    draw_card(c, 570, h - 132, 368, 66)
    draw_text(c, "Readiness split", 584, h - 88, 8.4, muted, "Helvetica-Bold")
    split_x, split_y, split_w = 584, h - 111, 320
    c.setFillColor(colors.HexColor("#E6EBF3"))
    c.roundRect(split_x, split_y, split_w, 10, 5, fill=1, stroke=0)
    if summaries:
        ready_w = split_w * ready_count / len(summaries)
        partial_w = split_w * partial_count / len(summaries)
        c.setFillColor(success)
        c.roundRect(split_x, split_y, ready_w, 10, 5, fill=1, stroke=0)
        c.setFillColor(gold)
        c.rect(split_x + ready_w, split_y, partial_w, 10, fill=1, stroke=0)
        c.setFillColor(danger)
        c.roundRect(split_x + ready_w + partial_w, split_y, split_w - ready_w - partial_w, 10, 5, fill=1, stroke=0)
    draw_text(c, f"Ready {ready_count}   Partial {partial_count}   Needs data {needs_count}", 584, h - 126, 8.4, navy_dark, "Helvetica-Bold")

    left_x, top_y = 34, h - 154
    draw_card(c, left_x, 40, 640, top_y - 40)
    draw_text(c, "Function coverage by dataset", left_x + 16, top_y - 20, 13, navy_dark, "Helvetica-Bold")
    draw_text(c, "Counts are expected outcomes by folder label, not final measured model accuracy.", left_x + 16, top_y - 35, 8.4, muted)

    table_y = top_y - 58
    row_h = 42
    headers = [("Function", 16), ("Expected pass", 318), ("Expected fail", 406), ("Status", 492)]
    c.setFillColor(colors.HexColor("#F8FAFC"))
    c.roundRect(left_x + 12, table_y - 4, 616, 24, 6, fill=1, stroke=0)
    for label, offset in headers:
        draw_text(c, label, left_x + offset, table_y + 3, 7.7, muted, "Helvetica-Bold")

    y = table_y - row_h
    max_total = max((item.total for item in summaries), default=1)
    for item in summaries:
        c.setStrokeColor(line)
        c.line(left_x + 12, y + row_h - 8, left_x + 628, y + row_h - 8)
        draw_text(c, item.name, left_x + 16, y + 24, 9.1, navy_dark, "Helvetica-Bold")
        draw_wrapped(c, item.note, left_x + 16, y + 11, 280, 7.4, muted, leading=8.6)
        draw_text(c, f"{item.expected_pass:,}", left_x + 326, y + 20, 10, success, "Helvetica-Bold")
        draw_text(c, f"{item.expected_fail:,}", left_x + 414, y + 20, 10, danger, "Helvetica-Bold")
        draw_status_pill(c, item.status, left_x + 492, y + 15)
        bar_x, bar_y, bar_w = left_x + 572, y + 19, 48
        c.setFillColor(colors.HexColor("#E6EBF3"))
        c.roundRect(bar_x, bar_y, bar_w, 6, 3, fill=1, stroke=0)
        if item.total:
            c.setFillColor(navy)
            c.roundRect(bar_x, bar_y, max(2, bar_w * item.total / max_total), 6, 3, fill=1, stroke=0)
        y -= row_h

    right_x = 696
    draw_card(c, right_x, 258, 238, 122)
    draw_text(c, "Expected pass/fail balance", right_x + 14, 356, 12, navy_dark, "Helvetica-Bold")
    draw_text(c, "Expected pass", right_x + 14, 331, 8, muted, "Helvetica-Bold")
    draw_text(c, f"{expected_pass:,}", right_x + 174, 331, 12, success, "Helvetica-Bold")
    draw_text(c, "Expected fail", right_x + 14, 303, 8, muted, "Helvetica-Bold")
    draw_text(c, f"{expected_fail:,}", right_x + 174, 303, 12, danger, "Helvetica-Bold")
    if expected_total:
        c.setFillColor(colors.HexColor("#E6EBF3"))
        c.roundRect(right_x + 14, 317, 206, 9, 5, fill=1, stroke=0)
        c.setFillColor(success)
        c.roundRect(right_x + 14, 317, 206 * expected_pass / expected_total, 9, 5, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#E6EBF3"))
        c.roundRect(right_x + 14, 289, 206, 9, 5, fill=1, stroke=0)
        c.setFillColor(danger)
        c.roundRect(right_x + 14, 289, 206 * expected_fail / expected_total, 9, 5, fill=1, stroke=0)
    draw_wrapped(c, "Use this as a collection/readiness view until evaluation scripts produce measured accuracy.", right_x + 14, 277, 208, 7.4, muted, leading=8.6)

    draw_card(c, right_x, 40, 238, 210)
    draw_text(c, "Next data to collect", right_x + 14, 226, 12, navy_dark, "Helvetica-Bold")
    next_items = [
        "Active liveness videos for real face and screen replay on phone/tablet/laptop.",
        "Face login data: 20-30 enrolled identities, unknown users, printed photo, and screen replay.",
        "Printed passport and Lao ID copies: at least 50 real and 50 fake per document type.",
        "More real live selfies to balance the large spoof set and tune false rejects.",
    ]
    y = 206
    for index, text in enumerate(next_items, start=1):
        c.setFillColor(gold)
        c.circle(right_x + 18, y + 4, 5, fill=1, stroke=0)
        draw_text(c, str(index), right_x + 15.2, y + 1, 6, navy_dark, "Helvetica-Bold")
        y = draw_wrapped(c, text, right_x + 30, y + 7, 196, 8, muted, leading=9.6) - 8

    draw_text(c, "Generated: 2026-06-04 | Source: test_dataset folder counts", 34, 18, 7.5, muted)
    draw_text(c, "Important: expected pass/fail labels are not final NIST/IAL2 accuracy evidence.", 674, 18, 7.5, danger, "Helvetica-Bold")
    c.save()


if __name__ == "__main__":
    build_pdf()
    print(OUTPUT)
