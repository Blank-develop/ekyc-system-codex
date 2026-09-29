"""Build docs/system-workflow.pdf and .png: one-page end-to-end flowchart.

Renders an A4-landscape workflow of the Kyron eKYC pipeline with headless
Google Chrome, following the same pattern as build_hand_gesture_guide_pdf.py.

Usage:
    python3 scripts/build_system_workflow_pdf.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PDF = ROOT / "docs" / "system-workflow.pdf"
OUTPUT_PNG = ROOT / "docs" / "system-workflow.png"
HTML_PATH = ROOT / "outputs" / "system_workflow.html"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

NAVY = "#081632"
NAVY_MID = "#10255a"
GOLD = "#d9ae27"
BG = "#f6f8fc"
LINE = "#dbe2ef"
MUTED = "#5a6478"
GREEN = "#13795b"
RED = "#a3262d"

MAIN_STEPS = [
    (
        "1 · Start session",
        "browser + API",
        [
            "User enters a real <b>user_id</b>",
            "<b>POST /api/verifications</b>",
            "Assigns 3 random face actions",
            "Assigns 3 hand gestures (max 1 tricky)",
        ],
    ),
    (
        "2 · Document proofing",
        "backend analysis",
        [
            "Passport / Lao ID upload or camera",
            "Quality: sharpness, glare, contrast",
            "OCR + TD3 MRZ check digits (hard fail)",
            "Recapture, tamper + model ensemble",
            "Portrait face embedding kept in session",
        ],
    ),
    (
        "3 · Active liveness",
        "browser + backend",
        [
            "Blink / turn head / open mouth",
            "FaceMesh detects the action live",
            "3-frame evidence burst to backend",
            "Backend rejects screen/photo replay",
        ],
    ),
    (
        "4 · Hand gesture",
        "browser",
        [
            "3 gestures from 23-gesture catalog",
            "MediaPipe Hands tracks the hand",
            "Hold gesture inside the moving circle",
            "Progress ring completes each pass",
        ],
    ),
    (
        "5 · Selfie match + PAD",
        "backend analysis",
        [
            "10-frame live burst",
            "Face-size gate: fill the yellow circle",
            "facenox PAD + replay heuristics",
            "Natural motion / lighting checks",
            "SFace match vs document portrait ≥ 0.68",
        ],
    ),
]

OUTCOME_STEPS = [
    (
        "Enroll Face ID",
        "optional, after pass",
        [
            "<b>POST .../enroll-face</b>",
            "One active Face ID per user_id",
            "One profile per passport number",
            "SQLAlchemy: SQLite / PostgreSQL",
        ],
    ),
    (
        "Returning face login",
        "any later visit",
        [
            "<b>POST /api/face-login</b>",
            "Passive liveness first, then match",
            "SFace vs enrolled templates",
            "Returns the verified profile",
        ],
    ),
    (
        "Face Pay demo",
        "payment-style action",
        [
            "Transfer confirmed by Face ID",
            "Shows bank-style authorization",
            "Uses the same login pipeline",
        ],
    ),
]


def step_box(title: str, tag: str, bullets: list[str], accent: str = GOLD) -> str:
    items = "".join(f"<li>{b}</li>" for b in bullets)
    return (
        f'<div class="step" style="border-top-color:{accent}">'
        f'<h3>{title}</h3><span class="tag">{tag}</span><ul>{items}</ul></div>'
    )


def build_html() -> str:
    main_row = '<span class="arrow">→</span>'.join(step_box(*s) for s in MAIN_STEPS)
    outcome_row = '<span class="arrow">→</span>'.join(step_box(*s, accent=GREEN) for s in OUTCOME_STEPS)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<style>
  @page {{ size: A4 landscape; margin: 0; }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    width: 1123px; height: 794px;
    font-family: "Helvetica Neue", Arial, sans-serif;
    background: {BG}; color: {NAVY};
    display: flex; flex-direction: column;
  }}
  header {{
    background: {NAVY}; color: white;
    padding: 16px 30px 14px; border-bottom: 4px solid {GOLD};
    display: flex; align-items: baseline; gap: 14px;
  }}
  header .brand {{ font-size: 11px; letter-spacing: 2.5px; text-transform: uppercase; color: {GOLD}; }}
  header h1 {{ font-size: 19px; font-weight: 700; }}
  header p {{ font-size: 11px; color: #c6cfe3; margin-left: auto; }}
  main {{ padding: 16px 24px 0; flex: 1; display: flex; flex-direction: column; justify-content: space-evenly; }}
  .row {{ display: flex; align-items: stretch; gap: 0; }}
  .step {{
    flex: 1; background: white; border: 1px solid {LINE}; border-top: 4px solid {GOLD};
    border-radius: 8px; padding: 12px 12px; min-height: 168px;
  }}
  .step h3 {{ font-size: 13.5px; margin-bottom: 3px; }}
  .step .tag {{
    display: inline-block; font-size: 9.5px; font-weight: 700; letter-spacing: 0.6px;
    text-transform: uppercase; color: {NAVY_MID}; background: {BG};
    border: 1px solid {LINE}; border-radius: 4px; padding: 2px 7px; margin-bottom: 7px;
  }}
  .step ul {{ list-style: none; }}
  .step li {{
    font-size: 11px; color: {MUTED}; line-height: 1.52; padding-left: 10px; position: relative;
  }}
  .step li::before {{ content: "•"; position: absolute; left: 0; color: {GOLD}; }}
  .arrow {{ align-self: center; font-size: 20px; font-weight: 700; color: {NAVY_MID}; padding: 0 6px; }}
  .decision-band {{
    display: flex; gap: 12px; margin: 14px 0;
    align-items: stretch;
  }}
  .decision {{
    flex: 0 0 260px; background: {NAVY}; color: white; border-radius: 8px;
    padding: 12px 14px; border-top: 4px solid {GOLD};
  }}
  .decision h3 {{ font-size: 13.5px; margin-bottom: 6px; color: white; }}
  .decision li {{ font-size: 11px; color: #c6cfe3; line-height: 1.55; list-style: none; padding-left: 10px; position: relative; }}
  .decision li::before {{ content: "•"; position: absolute; left: 0; color: {GOLD}; }}
  .outcome {{
    flex: 1; background: white; border: 1px solid {LINE}; border-radius: 8px; padding: 12px 14px;
  }}
  .outcome h4 {{ font-size: 12px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; }}
  .outcome.pass h4 {{ color: {GREEN}; }}
  .outcome.fail h4 {{ color: {RED}; }}
  .outcome.wait h4 {{ color: {NAVY_MID}; }}
  .outcome p {{ font-size: 11px; color: {MUTED}; line-height: 1.55; }}
  .section-label {{
    font-size: 11.5px; font-weight: 700; letter-spacing: 1.2px; text-transform: uppercase;
    color: {NAVY_MID}; margin: 8px 0 7px;
  }}
  footer {{
    margin: 10px 24px 14px; padding: 10px 16px;
    background: white; border: 1px solid {LINE}; border-left: 4px solid {GOLD}; border-radius: 0 8px 8px 0;
    font-size: 10.5px; color: {MUTED}; line-height: 1.55;
  }}
</style>
</head>
<body>
  <header>
    <span class="brand">Kyron eKYC</span>
    <h1>End-to-end verification workflow</h1>
    <p>FastAPI backend · React/Vite frontend · local open-source AI models · no raw image storage</p>
  </header>
  <main>
    <p class="section-label">Verification flow — every step must pass</p>
    <div class="row">{main_row}</div>

    <div class="decision-band">
      <div class="decision">
        <h3>Decision engine</h3>
        <ul>
          <li>Recomputed after every step</li>
          <li>Any hard-fail signal → <b>rejected</b></li>
          <li>All checks passed → <b>passed</b></li>
          <li>Otherwise → <b>pending</b></li>
          <li>Explainable reason codes + scores</li>
        </ul>
      </div>
      <div class="outcome pass">
        <h4>Passed</h4>
        <p>All checks green: document genuine, person live, gestures done, selfie matches the document portrait. Unlocks Face ID enrollment below.</p>
      </div>
      <div class="outcome fail">
        <h4>Rejected</h4>
        <p>Hard fail: unreadable/expired document, invalid MRZ, replay or spoof evidence, failed challenge, or face match below threshold. User gets an actionable message and can retry the step.</p>
      </div>
      <div class="outcome wait">
        <h4>Pending</h4>
        <p>Steps remain. Reason codes such as PASSIVE_LIVENESS_REQUIRED show exactly what is still missing.</p>
      </div>
    </div>

    <p class="section-label">After a passed verification — returning user</p>
    <div class="row">{outcome_row}</div>
  </main>
  <footer>
    Privacy: raw passport and selfie images are analyzed in memory and never stored. Only face templates (after consented enrollment),
    scores, reason codes, and timestamps persist. Thresholds are tunable via LALIGENCE_* environment variables.
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
        "--window-size=1123,794",
        "--force-device-scale-factor=2",
        "--hide-scrollbars",
        url,
    ])

    print(f"Wrote {OUTPUT_PDF}")
    print(f"Wrote {OUTPUT_PNG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
