"""Build docs/hand-gesture-guide.pdf and .png from the gesture prompt catalog.

Renders a one-page branded guide with headless Chrome so the gesture emoji
match what users see in the web app. Requires Google Chrome.

Usage:
    python3 scripts/build_hand_gesture_guide_pdf.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PDF = ROOT / "docs" / "hand-gesture-guide.pdf"
OUTPUT_PNG = ROOT / "docs" / "hand-gesture-guide.png"
HTML_PATH = ROOT / "outputs" / "hand_gesture_guide.html"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

NAVY = "#081632"
NAVY_MID = "#10255a"
GOLD = "#d9ae27"
BG = "#f6f8fc"
LINE = "#dbe2ef"
MUTED = "#5a6478"

SECTIONS: list[tuple[str, list[tuple[str, str, str]]]] = [
    (
        "Counting gestures — easy",
        [
            ("1️⃣", "Show 1", "Raise one finger."),
            ("2️⃣", "Show 2", "Raise two fingers."),
            ("3️⃣", "Show 3", "Raise three fingers."),
            ("4️⃣", "Show 4", "Raise four fingers."),
            ("5️⃣", "Show 5", "All five fingers, open hand."),
            ("☝️", "Point up", "Point one finger up."),
            ("✌️", "Peace / victory", "Index and middle finger in a V."),
        ],
    ),
    (
        "Palm and fist — easy",
        [
            ("✋", "Open palm / stop", "Open hand, fingers spread."),
            ("\U0001f590️", "High five", "Open hand like a high five."),
            ("✊", "Fist", "Close your hand into a fist."),
        ],
    ),
    (
        "Thumb and pinch — easy",
        [
            ("\U0001f44d", "Thumb up", "Make a fist, point your thumb up."),
            ("\U0001f44c", "OK / pinch", "Thumb and index fingertip in a ring."),
            ("\U0001f90c", "Pinched fingers", "All fingertips together, pointing up."),
            ("L", "L shape", "Thumb and index finger form an L."),
        ],
    ),
    (
        "Trickier — at most one per session",
        [
            ("\U0001f44e", "Thumb down", "Make a fist, point your thumb down."),
            ("\U0001f918", "Rock on", "Raise index and pinky fingers."),
            ("\U0001f91f", "I love you", "Raise thumb, index, and pinky."),
            ("\U0001f919", "Call me", "Extend thumb and pinky."),
            ("\U0001f91e", "Crossed fingers", "Cross index over middle finger."),
        ],
    ),
]

TIPS = [
    "Each session asks for 3 random gestures; at least 2 are from the easy set.",
    "Move your hand inside the circle, make the gesture, and hold it until the gold ring completes.",
    "Use good lighting, face your palm to the camera, and keep your whole hand visible.",
]


def gesture_card(visual: str, name: str, howto: str) -> str:
    return (
        '<div class="card">'
        f'<span class="visual">{visual}</span>'
        f"<div><strong>{name}</strong><small>{howto}</small></div>"
        "</div>"
    )


def build_html() -> str:
    sections_html = ""
    for label, gestures in SECTIONS:
        cards = "".join(gesture_card(*gesture) for gesture in gestures)
        sections_html += f'<p class="section-label">{label}</p><div class="grid">{cards}</div>'
    tips_html = "".join(f"<li>{tip}</li>" for tip in TIPS)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<style>
  @page {{ size: A4 portrait; margin: 0; }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    width: 794px; height: 1123px;
    font-family: "Helvetica Neue", Arial, sans-serif;
    background: {BG}; color: {NAVY};
    display: flex; flex-direction: column;
  }}
  header {{
    background: {NAVY}; color: white;
    padding: 26px 36px 22px; border-bottom: 4px solid {GOLD};
  }}
  header h1 {{ font-size: 24px; font-weight: 700; }}
  header p {{ margin-top: 6px; font-size: 12.5px; color: #c6cfe3; }}
  header .brand {{ font-size: 12px; letter-spacing: 2.5px; text-transform: uppercase; color: {GOLD}; margin-bottom: 8px; }}
  main {{ padding: 22px 36px 0; }}
  .section-label {{
    font-size: 11.5px; font-weight: 700; letter-spacing: 1.2px; text-transform: uppercase;
    color: {NAVY_MID}; margin: 14px 0 8px;
  }}
  .grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }}
  .card {{
    display: flex; align-items: center; gap: 9px;
    background: white; border: 1px solid {LINE}; border-radius: 8px;
    padding: 9px 10px; min-height: 56px;
  }}
  .visual {{
    flex: none; width: 34px; height: 34px; display: flex; align-items: center; justify-content: center;
    background: {BG}; border: 1px solid {LINE}; border-radius: 8px;
    font-size: 19px; font-weight: 700;
  }}
  .card strong {{ display: block; font-size: 12.5px; }}
  .card small {{ display: block; font-size: 10.5px; color: {MUTED}; line-height: 1.35; margin-top: 2px; }}
  footer {{
    margin: 18px 36px 0; padding: 14px 18px 16px; margin-bottom: 26px;
    background: white; border: 1px solid {LINE}; border-left: 4px solid {GOLD}; border-radius: 0 8px 8px 0;
  }}
  footer h2 {{ font-size: 12px; text-transform: uppercase; letter-spacing: 1.2px; color: {NAVY_MID}; margin-bottom: 6px; }}
  footer li {{ font-size: 11.5px; color: {MUTED}; line-height: 1.6; margin-left: 16px; }}
</style>
</head>
<body>
  <header>
    <div class="brand">Kyron eKYC</div>
    <h1>Hand gesture guide</h1>
    <p>Every gesture used in the verification challenge, with simple instructions.</p>
  </header>
  <main>{sections_html}</main>
  <footer>
    <h2>How the challenge works</h2>
    <ul>{tips_html}</ul>
  </footer>
</body>
</html>
"""


def run_chrome(args: list[str]) -> None:
    subprocess.run(
        [CHROME, "--headless", "--disable-gpu", "--no-first-run", *args],
        check=True,
        capture_output=True,
    )


def main() -> int:
    if not Path(CHROME).exists():
        print(f"Google Chrome not found at {CHROME}", file=sys.stderr)
        return 1
    HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
    HTML_PATH.write_text(build_html(), encoding="utf-8")
    url = HTML_PATH.resolve().as_uri()

    run_chrome([f"--print-to-pdf={OUTPUT_PDF}", "--no-pdf-header-footer", url])
    run_chrome([
        f"--screenshot={OUTPUT_PNG}",
        "--window-size=794,1123",
        "--force-device-scale-factor=2",
        "--hide-scrollbars",
        url,
    ])

    print(f"Wrote {OUTPUT_PDF}")
    print(f"Wrote {OUTPUT_PNG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
