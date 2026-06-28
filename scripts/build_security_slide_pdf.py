"""Build docs/security-slide.pdf (+ per-slide PNGs): a detailed, plain-English
security walkthrough for a management/boss presentation.

One slide per fix, each structured as: The problem -> What we did -> How we
tested it (with the result). Derived from docs/security-test-cases.md.

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
OUT_DIR = ROOT / "docs"
WORK = ROOT / "outputs"
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
RED = "#a3262d"
ICE = "#dde5f2"


def logo_data_uri() -> str:
    if not LOGO_PATH.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")


LOGO = logo_data_uri()


# Each fix: (tag, emoji, title, problem, did, test_lines, badges, cases)
FIXES = [
    (
        "Access control",
        "🔑",
        "We locked the “staff-only” data door",
        "A hidden admin page listed <b>everyone’s saved passport details</b> — and it had <b>no lock</b>. Anyone on the internet could open it and read all of it (and even delete everything).",
        "We put a lock on it. It now needs a secret key, and with <b>no key it is fully disabled</b>. We also applied the same lock on the public online demo, not just locally.",
        [
            "No key → door stays shut",
            "Wrong key → shut",
            "Correct key → opens",
            "“Delete everyone” button locked the same way",
        ],
        [("No key", "403"), ("Wrong key", "401"), ("Right key", "200")],
        "A1–A6, A8",
    ),
    (
        "Data protection",
        "🧹",
        "We deleted the real personal data",
        "We discovered <b>3 real passports</b> (yours + 2 others), with face data, were actually stored inside the system — kept alive by a hidden file that re-created them.",
        "We found the hidden file, <b>deleted it</b>, and wiped the database so nothing re-appears.",
        [
            "Count the stored people in the database",
            "Check the hidden re-seed file is gone",
        ],
        [("People stored", "0"), ("Hidden file", "gone")],
        "A7",
    ),
    (
        "Data protection",
        "🪪",
        "We stopped leaking passport numbers",
        "When the system <b>recognised a returning face</b>, it handed back that person’s <b>full passport number</b>, name, and date of birth — to <b>anyone</b>, even a stranger holding a photo.",
        "Now it returns only a first name + a <b>blurred number</b> like <b>PA•••••43</b>, and hides the full name, date of birth, and expiry. Enough to greet “welcome back”, nothing sensitive.",
        [
            "Confirm full name, DOB, expiry are removed",
            "Confirm the document number is masked",
            "Confirm the greeting still works",
        ],
        [("Passport No.", "PA•••••43"), ("Name / DOB / expiry", "hidden")],
        "A10–A11",
    ),
    (
        "Abuse prevention",
        "🚦",
        "We blocked mass “face-fishing”",
        "An attacker could upload <b>thousands of faces very fast</b>, fishing to see which ones match a real saved person — to steal their identity. The old limit failed behind shared internet addresses.",
        "We added a <b>speed limit</b>: each person gets only a few tries per minute, plus a <b>total cap</b> so mass attempts are rejected — and it now reads the real visitor address behind the proxy.",
        [
            "Make too many attempts from one client",
            "Make too many attempts in total",
        ],
        [("Too many tries", "429 blocked")],
        "A12–A13",
    ),
    (
        "Anti-bypass",
        "✋",
        "We stopped people faking the gesture step",
        "The hand-gesture step trusted the app to simply say “I did it.” A cheater could <b>skip the gesture entirely</b> by sending a fake “done!”, or <b>replay</b> an old “done!” message.",
        "The server now issues a <b>one-time ticket</b> per gesture (used once, then dead — no replay), and you <b>cannot do the gesture step</b> until the earlier, properly-checked steps have passed.",
        [
            "Try the gesture before the verified step → blocked",
            "No valid ticket → blocked",
            "Reuse a ticket (replay) → blocked",
        ],
        [("Skip ahead", "409"), ("No ticket", "401"), ("Replay", "401")],
        "A14–A16",
    ),
]


def chip(label: str, value: str) -> str:
    return f'<span class="chip"><em>{label}</em><b>{value}</b></span>'


def fix_slide(index: int, total: int, fix) -> str:
    tag, emoji, title, problem, did, test_lines, badges, cases = fix
    tests = "".join(f"<li>{t}</li>" for t in test_lines)
    chips = "".join(chip(label, value) for label, value in badges)
    logo_img = f'<img class="logo" src="{LOGO}" alt="Kyron" />' if LOGO else ""
    return f"""
  <header>
    {logo_img}
    <div class="titles"><span class="brand">KYRON eKYC · SECURITY</span><h1>{emoji} {title}</h1></div>
    <div class="badge">{tag}<br/><b>Fix {index} of {total}</b></div>
  </header>
  <main>
    <div class="block problem"><div class="blab">The problem</div><p>{problem}</p></div>
    <div class="block did"><div class="blab">What we did</div><p>{did}</p></div>
    <div class="block test">
      <div class="blab">How we tested it</div>
      <ul>{tests}</ul>
      <div class="chips">{chips}<span class="pass">✓ PASS</span></div>
    </div>
  </main>
  <footer>Documented test case(s) <b>{cases}</b> in <b>docs/security-test-cases.md</b> · reproducible via <b>docs/security-test-runbook.md</b>.</footer>
"""


def title_slide() -> str:
    logo_img = f'<img class="logo" src="{LOGO}" alt="Kyron" />' if LOGO else ""
    return f"""
  <header>
    {logo_img}
    <div class="titles"><span class="brand">KYRON eKYC</span><h1>What we did for security</h1></div>
    <div class="badge">Demo / prototype<br/><b>sample documents only</b></div>
  </header>
  <main class="cover">
    <p class="lede">Think of Kyron as a <b>building that checks people’s IDs</b>. Over this work we found and
    locked every weak door — explained here in plain language, each one proven with a test.</p>
    <div class="stats">
      <div class="stat"><div class="num">5</div><div class="lab">Weak spots fixed</div></div>
      <div class="stat"><div class="num">16/16</div><div class="lab">Test cases passed</div></div>
      <div class="stat"><div class="num">86</div><div class="lab">Automated tests</div></div>
      <div class="stat"><div class="num">0</div><div class="lab">Regressions</div></div>
    </div>
    <p class="agenda"><b>The 5 fixes:</b> &nbsp;1) Locked the staff data door &nbsp;·&nbsp; 2) Deleted real personal data
    &nbsp;·&nbsp; 3) Stopped leaking passport numbers &nbsp;·&nbsp; 4) Blocked mass face-fishing &nbsp;·&nbsp; 5) Stopped gesture faking</p>
  </main>
  <footer>Every fix below has a plain-English “problem → what we did → how we tested it”, plus a passing test.</footer>
"""


def closing_slide() -> str:
    proof = [
        ("86 automated tests", "The computer re-checks every rule itself — fast and repeatable (one command)."),
        ("16 documented test cases", "Each with objective, steps, and expected vs actual result — all PASS."),
        ("Live checks on the deployed demo", "Poking the real website returns “blocked”: 403 / 401 / 429."),
        ("Normal use still works", "A regular person can still complete a verification — nothing broke."),
    ]
    road = [
        "Encrypt stored face data &amp; details (with proper key management)",
        "Add real accounts / login for the main steps (in the production product)",
        "Fully check the gesture on the server (a hand model, not the app’s word)",
        "Bigger-scale rate limiting + activity logs for production",
    ]
    proof_html = "".join(
        f'<div class="row"><div class="tick g">✓</div><div class="fix-body"><strong>{t}</strong><span>{d}</span></div></div>'
        for t, d in proof
    )
    road_html = "".join(f'<div class="row"><div class="tick o">→</div><div class="fix-body"><strong>{t}</strong></div></div>' for t in road)
    return f"""
  <header>
    <div class="titles"><span class="brand">KYRON eKYC · SECURITY</span><h1>Proven — and the road ahead</h1></div>
    <div class="badge">Honest status<br/><b>aligned, not yet certified</b></div>
  </header>
  <main class="two-col">
    <section class="col"><h2 class="col-title green">How we proved it</h2>{proof_html}</section>
    <section class="col"><h2 class="col-title gold">Next, for production</h2>{road_html}</section>
  </main>
  <footer>Designed toward <b>NIST IAL2</b> · liveness built to <b>ISO/IEC 30107-3</b> · passport checks per <b>ICAO 9303</b>. Formal certification (ISO 30107-3 PAD, ISO 27001 / SOC 2) pending independent assessment.</footer>
"""


CSS = f"""
  @page {{ size: 1280px 720px; margin: 0; }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: "Helvetica Neue", Arial, sans-serif; background: {BG}; color: {NAVY}; }}
  .slide {{ width: 1280px; height: 720px; background: {BG}; display: flex; flex-direction: column; overflow: hidden; }}
  .slide + .slide {{ page-break-before: always; }}
  header {{ background: {NAVY}; color: white; padding: 18px 40px; border-bottom: 4px solid {GOLD};
    display: flex; align-items: center; gap: 16px; }}
  header .logo {{ height: 44px; }}
  header .titles {{ display: flex; flex-direction: column; }}
  header .brand {{ font-size: 11px; letter-spacing: 2.5px; color: {GOLD}; }}
  header h1 {{ font-size: 27px; font-weight: 700; margin-top: 3px; }}
  header .badge {{ margin-left: auto; text-align: right; font-size: 11px; color: {ICE}; line-height: 1.5; }}
  header .badge b {{ color: white; }}
  main {{ flex: 1; padding: 24px 40px 6px; display: flex; flex-direction: column; gap: 16px; }}
  .block {{ background: white; border: 1px solid {LINE}; border-left: 5px solid {MUTED}; border-radius: 10px; padding: 14px 18px; }}
  .block.problem {{ border-left-color: {RED}; }}
  .block.did {{ border-left-color: {GREEN}; }}
  .block.test {{ border-left-color: {GOLD}; flex: 1; }}
  .blab {{ font-size: 11.5px; text-transform: uppercase; letter-spacing: 1px; font-weight: 800; margin-bottom: 6px; }}
  .problem .blab {{ color: {RED}; }} .did .blab {{ color: {GREEN}; }} .test .blab {{ color: {GOLD_DK}; }}
  .block p {{ font-size: 15px; color: {NAVY_MID}; line-height: 1.5; }}
  .block b {{ color: {NAVY}; }}
  .test ul {{ margin: 0 0 0 4px; list-style: none; display: grid; gap: 4px; }}
  .test li {{ font-size: 13.5px; color: {MUTED}; padding-left: 16px; position: relative; line-height: 1.4; }}
  .test li::before {{ content: "•"; position: absolute; left: 2px; color: {GOLD}; }}
  .chips {{ margin-top: 10px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
  .chip {{ background: {BG}; border: 1px solid {LINE}; border-radius: 999px; padding: 4px 11px; font-size: 12px; }}
  .chip em {{ font-style: normal; color: {MUTED}; }} .chip b {{ color: {NAVY}; margin-left: 6px; }}
  .pass {{ background: {GREEN}; color: white; border-radius: 999px; padding: 4px 12px; font-size: 12px; font-weight: 800; }}
  footer {{ margin: 6px 40px 16px; padding: 10px 16px; background: white; border: 1px solid {LINE};
    border-left: 4px solid {GOLD}; border-radius: 0 8px 8px 0; font-size: 10.5px; color: {MUTED}; line-height: 1.5; }}
  footer b {{ color: {NAVY}; }}
  /* cover */
  .cover {{ justify-content: center; gap: 22px; }}
  .lede {{ font-size: 19px; color: {NAVY_MID}; line-height: 1.55; max-width: 1050px; }}
  .lede b {{ color: {NAVY}; }}
  .stats {{ display: flex; gap: 16px; }}
  .stat {{ flex: 1; background: white; border: 1px solid {LINE}; border-top: 4px solid {GOLD}; border-radius: 10px; padding: 14px; text-align: center; }}
  .stat .num {{ font-size: 44px; font-weight: 800; color: {NAVY}; line-height: 1; }}
  .stat .lab {{ font-size: 12.5px; color: {MUTED}; margin-top: 6px; font-weight: 600; }}
  .agenda {{ font-size: 13.5px; color: {MUTED}; line-height: 1.6; }}
  .agenda b {{ color: {NAVY}; }}
  /* closing */
  .two-col {{ flex-direction: row; gap: 30px; padding-top: 22px; }}
  .col {{ flex: 1; display: flex; flex-direction: column; gap: 14px; }}
  .col-title {{ font-size: 14px; text-transform: uppercase; letter-spacing: 1px; font-weight: 800; padding-bottom: 8px; border-bottom: 2px solid {LINE}; }}
  .col-title.green {{ color: {GREEN}; }} .col-title.gold {{ color: {GOLD_DK}; }}
  .row {{ display: flex; gap: 11px; align-items: flex-start; }}
  .tick {{ flex: 0 0 auto; width: 24px; height: 24px; border-radius: 50%; color: white; font-size: 14px; font-weight: 800;
    display: flex; align-items: center; justify-content: center; margin-top: 1px; }}
  .tick.g {{ background: {GREEN}; }} .tick.o {{ background: {GOLD_DK}; }}
  .fix-body {{ display: flex; flex-direction: column; }}
  .fix-body strong {{ font-size: 14.5px; color: {NAVY}; }}
  .fix-body span {{ font-size: 12.5px; color: {MUTED}; line-height: 1.45; margin-top: 2px; }}
"""


def doc(*bodies: str) -> str:
    slides = "".join(f'<div class="slide">{b}</div>' for b in bodies)
    return f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/><style>{CSS}</style></head><body>{slides}</body></html>'


def run_chrome(args: list[str]) -> None:
    subprocess.run([CHROME, "--headless", "--disable-gpu", "--no-first-run", *args], check=True, capture_output=True)


def main() -> int:
    if not Path(CHROME).exists():
        print(f"Google Chrome not found at {CHROME}", file=sys.stderr)
        return 1
    WORK.mkdir(parents=True, exist_ok=True)

    bodies = [title_slide()]
    bodies += [fix_slide(i + 1, len(FIXES), fix) for i, fix in enumerate(FIXES)]
    bodies.append(closing_slide())

    combined = WORK / "security_slide_combined.html"
    combined.write_text(doc(*bodies), encoding="utf-8")
    run_chrome([f"--print-to-pdf={OUT_PDF}", "--no-pdf-header-footer", combined.resolve().as_uri()])
    print(f"Wrote {OUT_PDF} ({len(bodies)} slides)")

    # clean old per-slide PNGs, then render each
    for old in OUT_DIR.glob("security-slide-*.png"):
        old.unlink()
    for i, body in enumerate(bodies, start=1):
        html = WORK / f"security_slide_{i}.html"
        html.write_text(doc(body), encoding="utf-8")
        png = OUT_DIR / f"security-slide-{i}.png"
        run_chrome([f"--screenshot={png}", "--window-size=1280,720", "--force-device-scale-factor=2",
                    "--hide-scrollbars", html.resolve().as_uri()])
        print(f"Wrote {png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
