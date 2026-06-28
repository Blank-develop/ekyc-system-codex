"""Build docs/security-slide.pdf (+ PNGs): a 2-slide security summary for a
management/boss presentation, derived from docs/security-test-cases.md.

Slide 1 — what we delivered (7 fixes + headline numbers).
Slide 2 — how we proved it + the honest production roadmap.

Renders with headless Google Chrome, same Kyron brand as build_results_slide_pdf.py.

Usage:
    python3 scripts/build_security_slide_pdf.py
"""

from __future__ import annotations

import base64
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_PDF = ROOT / "docs" / "security-slide.pdf"
OUT_PNG1 = ROOT / "docs" / "security-slide-1.png"
OUT_PNG2 = ROOT / "docs" / "security-slide-2.png"
HTML1 = ROOT / "outputs" / "security_slide_1.html"
HTML2 = ROOT / "outputs" / "security_slide_2.html"
HTML_COMBINED = ROOT / "outputs" / "security_slide_combined.html"
LOGO_PATH = ROOT / "kyron.png"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

NAVY = "#071b4a"
NAVY_MID = "#10255a"
GOLD = "#d9ae27"
GOLD_DK = "#c9a12a"
BG = "#f6f8fc"
LINE = "#dbe2ef"
MUTED = "#5a6478"
GREEN = "#13795b"
ICE = "#dde5f2"
WHITE = "#ffffff"


def logo_data_uri() -> str:
    if not LOGO_PATH.exists():
        return ""
    encoded = base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


FIXES = [
    ("Admin data endpoints locked",
     "The “list everyone’s data” page now needs a secret key; with no key it is disabled (fail-closed)."),
    ("Real personal data purged",
     "Found 3 real passports (+ face templates) stored and re-seeding; deleted the source and wiped the store."),
    ("Public demo locked too",
     "The same admin endpoints return 403 on the hosted demo, not just locally."),
    ("Face-login hides passport details",
     "On a match it returns first name + a masked document number (PA•••••43); no full name / DOB / expiry."),
    ("Anti brute-force throttle",
     "Per-client + global rate limit on face matching blocks mass “face-fishing”, even behind shared proxy IPs."),
    ("Gesture step can’t be faked",
     "One-time server-issued token (replay-proof) + can’t skip ahead before the server-verified liveness step."),
]

ROADMAP = [
    ("Encrypt biometric templates &amp; PII at rest", "with proper key management (KMS)"),
    ("API authentication", "for verification + face-login, when accounts / partners are added"),
    ("Full server-side gesture verification", "a backend hand model instead of trusting the client"),
    ("Distributed rate limiting + audit logs", "for multi-instance production scale"),
]


def slide1_body() -> str:
    logo = logo_data_uri()
    logo_img = f'<img class="logo" src="{logo}" alt="Kyron" />' if logo else ""
    cards = "".join(
        f'<div class="fix"><div class="tick">✓</div>'
        f'<div class="fix-body"><strong>{title}</strong><span>{desc}</span></div></div>'
        for title, desc in FIXES
    )
    return f"""
  <header>
    {logo_img}
    <div class="titles"><span class="brand">KYRON eKYC</span><h1>Security hardening — what we delivered</h1></div>
    <div class="badge">Demo / prototype<br/><b>sample documents only</b></div>
  </header>
  <main>
    <div class="stats">
      <div class="stat"><div class="num">7</div><div class="lab">Security issues fixed</div></div>
      <div class="stat"><div class="num">16/16</div><div class="lab">Test cases passed</div></div>
      <div class="stat"><div class="num">86</div><div class="lab">Automated tests passing</div></div>
      <div class="stat"><div class="num">0</div><div class="lab">Regressions</div></div>
    </div>
    <div class="fixes">{cards}</div>
  </main>
  <footer>Every fix is backed by an automated test and a documented case (A1–A16) in <b>docs/security-test-cases.md</b>.</footer>
"""


def slide2_body() -> str:
    proof = [
        ("86 automated tests", "The computer re-checks every rule — fast and repeatable (one command)."),
        ("16 documented test cases", "Each with objective, steps, expected vs actual result — all PASS."),
        ("Live checks on the deployed demo", "Poking the real site returns “blocked”: 403 / 401 / 429."),
    ]
    proof_html = "".join(
        f'<div class="row"><div class="tick g">✓</div><div class="fix-body"><strong>{t}</strong><span>{d}</span></div></div>'
        for t, d in proof
    )
    road_html = "".join(
        f'<div class="row"><div class="tick o">→</div><div class="fix-body"><strong>{t}</strong><span>{d}</span></div></div>'
        for t, d in ROADMAP
    )
    return f"""
  <header>
    <div class="titles"><span class="brand">KYRON eKYC</span><h1>Proven — and the road ahead</h1></div>
    <div class="badge">Honest status<br/><b>aligned, not yet certified</b></div>
  </header>
  <main class="two-col">
    <section class="col">
      <h2 class="col-title green">How we proved it</h2>
      {proof_html}
    </section>
    <section class="col">
      <h2 class="col-title gold">Next on the production roadmap</h2>
      {road_html}
    </section>
  </main>
  <footer>Designed toward <b>NIST IAL2</b> · liveness built to <b>ISO/IEC 30107-3</b> · passport checks per <b>ICAO 9303</b>. Production certification (ISO 30107-3 PAD, ISO 27001 / SOC 2) pending independent assessment.</footer>
"""


CSS = f"""
  @page {{ size: 1280px 720px; margin: 0; }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: "Helvetica Neue", Arial, sans-serif; background: {BG}; color: {NAVY}; }}
  .slide {{ width: 1280px; height: 720px; background: {BG}; display: flex; flex-direction: column; overflow: hidden; }}
  .slide + .slide {{ page-break-before: always; }}
  header {{ background: {NAVY}; color: white; padding: 18px 36px; border-bottom: 4px solid {GOLD};
    display: flex; align-items: center; gap: 16px; }}
  header .logo {{ height: 44px; width: auto; }}
  header .titles {{ display: flex; flex-direction: column; }}
  header .brand {{ font-size: 11px; letter-spacing: 3px; color: {GOLD}; }}
  header h1 {{ font-size: 23px; font-weight: 700; margin-top: 2px; }}
  header .badge {{ margin-left: auto; text-align: right; font-size: 11px; color: {ICE}; line-height: 1.5; }}
  header .badge b {{ color: white; }}
  main {{ flex: 1; padding: 22px 36px 8px; display: flex; flex-direction: column; }}
  .stats {{ display: flex; gap: 16px; margin-bottom: 18px; }}
  .stat {{ flex: 1; background: white; border: 1px solid {LINE}; border-top: 4px solid {GOLD}; border-radius: 10px;
    padding: 12px 14px; text-align: center; }}
  .stat .num {{ font-size: 40px; font-weight: 800; color: {NAVY}; line-height: 1; }}
  .stat .lab {{ font-size: 12px; color: {MUTED}; margin-top: 6px; font-weight: 600; }}
  .fixes {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px 18px; }}
  .fix, .row {{ display: flex; gap: 11px; align-items: flex-start; }}
  .tick {{ flex: 0 0 auto; width: 24px; height: 24px; border-radius: 50%; background: {GREEN}; color: white;
    font-size: 14px; font-weight: 800; display: flex; align-items: center; justify-content: center; margin-top: 1px; }}
  .tick.g {{ background: {GREEN}; }}
  .tick.o {{ background: {GOLD_DK}; }}
  .fix-body {{ display: flex; flex-direction: column; }}
  .fix-body strong {{ font-size: 14.5px; color: {NAVY}; }}
  .fix-body span {{ font-size: 12px; color: {MUTED}; line-height: 1.45; margin-top: 2px; }}
  .two-col {{ flex-direction: row; gap: 30px; }}
  .col {{ flex: 1; display: flex; flex-direction: column; gap: 16px; }}
  .col-title {{ font-size: 14px; text-transform: uppercase; letter-spacing: 1px; font-weight: 800;
    padding-bottom: 8px; border-bottom: 2px solid {LINE}; }}
  .col-title.green {{ color: {GREEN}; }}
  .col-title.gold {{ color: {GOLD_DK}; }}
  footer {{ margin: 8px 36px 16px; padding: 10px 16px; background: white; border: 1px solid {LINE};
    border-left: 4px solid {GOLD}; border-radius: 0 8px 8px 0; font-size: 10.5px; color: {MUTED}; line-height: 1.5; }}
  footer b {{ color: {NAVY}; }}
"""


def page(body: str) -> str:
    return f'<div class="slide">{body}</div>'


def doc(*bodies: str) -> str:
    slides = "".join(page(b) for b in bodies)
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/><style>{CSS}</style></head>
<body>{slides}</body></html>"""


def run_chrome(args: list[str]) -> None:
    subprocess.run([CHROME, "--headless", "--disable-gpu", "--no-first-run", *args], check=True, capture_output=True)


def main() -> int:
    if not Path(CHROME).exists():
        print(f"Google Chrome not found at {CHROME}", file=sys.stderr)
        return 1
    HTML1.parent.mkdir(parents=True, exist_ok=True)
    HTML1.write_text(doc(slide1_body()), encoding="utf-8")
    HTML2.write_text(doc(slide2_body()), encoding="utf-8")
    HTML_COMBINED.write_text(doc(slide1_body(), slide2_body()), encoding="utf-8")

    run_chrome([f"--print-to-pdf={OUT_PDF}", "--no-pdf-header-footer", HTML_COMBINED.resolve().as_uri()])
    for html, png in ((HTML1, OUT_PNG1), (HTML2, OUT_PNG2)):
        run_chrome([f"--screenshot={png}", "--window-size=1280,720", "--force-device-scale-factor=2",
                    "--hide-scrollbars", html.resolve().as_uri()])

    print(f"Wrote {OUT_PDF}")
    print(f"Wrote {OUT_PNG1}")
    print(f"Wrote {OUT_PNG2}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
