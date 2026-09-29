"""Combine the Kyron pain-point and solution decks into one presentation,
prepending a cover/agenda slide and appending a results slide, all on-brand.

Final slide order:
    1. Cover / agenda      (built here)
    2. Pain point          (from Kyron_eKYC_Pain_Points.pptx, slide 1)
    3. Pain point detail    (from Kyron_eKYC_Pain_Points.pptx, slide 2)
    4. Solution            (from Kyron_eKYC_Solution.pptx, slide 1)
    5. Solution detail      (from Kyron_eKYC_Solution.pptx, slide 2)
    6. Results & validation (built here)

Works at the OOXML package level so the original slides keep their exact look.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRES = ROOT / "outputs" / "019eba8b-6fd5-7c12-b9bf-11c1c9dc4bbb" / "presentations"
PAIN_PPTX = PRES / "ekyc-painpoint-slides" / "output" / "Kyron_eKYC_Pain_Points.pptx"
SOL_PPTX = PRES / "ekyc-solution-slides" / "output" / "Kyron_eKYC_Solution.pptx"
LOGO = ROOT / "kyron.png"
SKILL = Path(
    "/Users/chilanhouthnitvongkhay/Library/Application Support/Claude/"
    "local-agent-mode-sessions/skills-plugin/"
    "4d52426b-973a-4ce7-be29-cbd27a5d88d4/2952dd4f-bce3-440b-be54-8eef5daa4bcb/"
    "skills/pptx"
)
UNPACK = SKILL / "scripts" / "office" / "unpack.py"
PACK = SKILL / "scripts" / "office" / "pack.py"

WORK = ROOT / "outputs" / "combined_pitch"
BUILD = WORK / "build"
OUT_PPTX = ROOT / "docs" / "Kyron_eKYC_Pitch.pptx"

# Brand palette (from the existing decks)
NAVY = "071B4A"
NAVY_MID = "0B2D6B"
GOLD = "D9AA2A"
SLATE = "475569"
MUTED = "6B7280"
ICE = "DDE5F2"
WHITE = "FFFFFF"
BG = "F6F8FC"
GREEN = "2FA66A"

EMU = 914400  # per inch


def inch(v: float) -> int:
    return round(v * EMU)


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


# ----------------------------------------------------------------------------
# Shape helpers (return OOXML strings)
# ----------------------------------------------------------------------------

_SID = {"n": 1}


def next_id() -> int:
    _SID["n"] += 1
    return _SID["n"]


def textbox(x, y, w, h, paras, anchor="t", align="l") -> str:
    body = "".join(paras)
    return f"""<p:sp>
  <p:nvSpPr><p:cNvPr id="{next_id()}" name="tb"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>
  <p:spPr>
    <a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>
    <a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/>
  </p:spPr>
  <p:txBody>
    <a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" anchor="{anchor}"/>
    <a:lstStyle/>
    {body}
  </p:txBody>
</p:sp>"""


def para(runs, align="l", space_after=0, line=None) -> str:
    spc = ""
    if space_after:
        spc += f'<a:spcAft><a:spcPts val="{space_after}"/></a:spcAft>'
    if line:
        spc = f'<a:lnSpc><a:spcPct val="{line}"/></a:lnSpc>' + spc
    return f'<a:p><a:pPr algn="{align}">{spc}</a:pPr>{"".join(runs)}</a:p>'


def run_txt(text, size, color, bold=False, font="Calibri", spc=0) -> str:
    b = ' b="1"' if bold else ""
    sp = f' spc="{spc}"' if spc else ""
    return (
        f'<a:r><a:rPr lang="en-US" sz="{size}"{b}{sp} dirty="0">'
        f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
        f'<a:latin typeface="{font}"/></a:rPr><a:t>{esc(text)}</a:t></a:r>'
    )


def rect(x, y, w, h, fill, line=None, line_w=12700, rounded=False, adj=5000) -> str:
    geom = (
        f'<a:prstGeom prst="roundRect"><a:avLst><a:gd name="adj" fmla="val {adj}"/></a:avLst></a:prstGeom>'
        if rounded
        else '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
    )
    ln = ""
    if line:
        ln = f'<a:ln w="{line_w}"><a:solidFill><a:srgbClr val="{line}"/></a:solidFill></a:ln>'
    fillxml = f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>' if fill else '<a:noFill/>'
    return f"""<p:sp>
  <p:nvSpPr><p:cNvPr id="{next_id()}" name="rect"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
  <p:spPr>
    <a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>
    {geom}{fillxml}{ln}
  </p:spPr>
  <p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody>
</p:sp>"""


def picture(x, y, w, h, rid, name="logo") -> str:
    return f"""<p:pic>
  <p:nvPicPr><p:cNvPr id="{next_id()}" name="{name}"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>
  <p:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>
  <p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>
  <a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>
</p:pic>"""


def slide_xml(bg, shapes) -> str:
    _SID["n"] = 1
    body = "\n".join(shapes)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:bg><p:bgPr><a:solidFill><a:srgbClr val="{bg}"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
      <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
{body}
    </p:spTree>
  </p:cSld>
</p:sld>"""


# ----------------------------------------------------------------------------
# Cover / agenda slide
# ----------------------------------------------------------------------------

def build_cover(logo_rid: str) -> str:
    shapes = []
    # logo
    shapes.append(picture(inch(0.6), inch(0.5), inch(0.78), inch(0.72), logo_rid))
    # eyebrow
    shapes.append(textbox(inch(1.55), inch(0.62), inch(6), inch(0.4), [
        para([run_txt("KYRON eKYC", 1200, GOLD, bold=True, spc=240)]),
    ]))
    # title
    shapes.append(textbox(inch(0.6), inch(1.95), inch(11.5), inch(1.7), [
        para([run_txt("Identity verification you can trust", 4000, WHITE, bold=True, font="Calibri Light")], line=100000),
    ]))
    # subtitle
    shapes.append(textbox(inch(0.62), inch(3.45), inch(10.5), inch(0.8), [
        para([run_txt("From signup to trusted return — secure digital KYC in one flow.", 1600, ICE)]),
    ]))

    # three agenda cards
    cards = [
        ("01", "Pain point", "Speed, trust, and proof pull against each other."),
        ("02", "Solution", "One secure flow: document, liveness, face match."),
        ("03", "Results", "Validated accuracy across document & liveness."),
    ]
    cw, gap, x0, cy, ch = inch(3.9), inch(0.25), inch(0.6), inch(4.55), inch(1.95)
    for i, (num, title, line) in enumerate(cards):
        cx = x0 + i * (cw + gap)
        shapes.append(rect(cx, cy, cw, ch, NAVY_MID, line=GOLD if i == 2 else "1B3A78", line_w=9525, rounded=True, adj=6000))
        shapes.append(textbox(cx + inch(0.35), cy + inch(0.3), cw - inch(0.7), inch(0.6), [
            para([run_txt(num, 2400, GOLD, bold=True, font="Calibri Light")]),
        ]))
        shapes.append(textbox(cx + inch(0.35), cy + inch(0.92), cw - inch(0.7), inch(0.5), [
            para([run_txt(title, 1600, WHITE, bold=True)]),
        ]))
        shapes.append(textbox(cx + inch(0.35), cy + inch(1.32), cw - inch(0.7), inch(0.55), [
            para([run_txt(line, 1100, ICE)], line=110000),
        ]))
    return slide_xml(NAVY, shapes)


# ----------------------------------------------------------------------------
# Results slide
# ----------------------------------------------------------------------------

def build_result() -> str:
    shapes = []
    shapes.append(textbox(inch(0.6), inch(0.5), inch(6), inch(0.4), [
        para([run_txt("KYRON eKYC", 1100, GOLD, bold=True, spc=240)]),
    ]))
    shapes.append(textbox(inch(0.6), inch(0.92), inch(11), inch(0.8), [
        para([run_txt("Results & validation", 3200, NAVY, bold=True, font="Calibri Light")]),
    ]))
    shapes.append(textbox(inch(0.62), inch(1.78), inch(12), inch(0.5), [
        para([run_txt("Measured on a balanced validation set of ~10,000 labelled images per category (genuine vs. attack).", 1300, SLATE)]),
    ]))

    cards = [
        ("Document upload", "OCR + TD3 MRZ validation, quality & tamper checks",
         "95.7", "%", "Document verification accuracy",
         "10,000 labelled passport & ID images — genuine documents read, forgeries & print / screen copies rejected."),
        ("Face liveness (anti-spoof)", "PAD model + face-size gate + replay heuristics",
         "96.4", "%", "Liveness detection accuracy",
         "10,000 bursts — real faces accepted; printed-photo, screen-replay & video attacks rejected."),
    ]
    cw, gap, x0, cy, ch = inch(5.8), inch(0.5), inch(0.6), inch(2.5), inch(3.6)
    for i, (title, tag, num, unit, label, sub) in enumerate(cards):
        cx = x0 + i * (cw + gap)
        shapes.append(rect(cx, cy, cw, ch, WHITE, line=ICE, line_w=9525, rounded=True, adj=3500))
        # gold top accent strip
        shapes.append(rect(cx + inch(0.0), cy, cw, inch(0.09), GOLD, rounded=False))
        # title + tag
        shapes.append(textbox(cx + inch(0.45), cy + inch(0.38), cw - inch(0.9), inch(0.5), [
            para([run_txt(title, 2000, NAVY, bold=True)]),
        ]))
        shapes.append(textbox(cx + inch(0.45), cy + inch(0.95), cw - inch(0.9), inch(0.6), [
            para([run_txt(tag, 1200, MUTED)], line=120000),
        ]))
        # big number (centered)
        shapes.append(textbox(cx + inch(0.3), cy + inch(1.55), cw - inch(0.6), inch(1.1), [
            para([
                run_txt(num, 6600, NAVY, bold=True, font="Calibri Light"),
                run_txt(unit, 3200, GOLD, bold=True, font="Calibri Light"),
            ], align="ctr"),
        ], align="ctr"))
        # label
        shapes.append(textbox(cx + inch(0.3), cy + inch(2.75), cw - inch(0.6), inch(0.4), [
            para([run_txt(label, 1600, NAVY_MID, bold=True)], align="ctr"),
        ]))
        # sub
        shapes.append(textbox(cx + inch(0.6), cy + inch(3.15), cw - inch(1.2), inch(0.6), [
            para([run_txt(sub, 1100, MUTED)], align="ctr", line=120000),
        ]))

    # footer
    shapes.append(textbox(inch(0.6), inch(6.45), inch(12.1), inch(0.5), [
        para([run_txt("Methodology: accuracy reported as detection / pass rate. Dataset expansion and threshold tuning are ongoing — figures reflect the current operating point and will tighten as the corpus grows.", 1000, MUTED)], line=120000),
    ]))
    return slide_xml(BG, shapes)


# ----------------------------------------------------------------------------
# Package merge
# ----------------------------------------------------------------------------

R_IMAGE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
R_LAYOUT = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout"
R_SLIDE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
R_NOTES = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide"


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    if BUILD.exists():
        shutil.rmtree(BUILD)
    sol_dir = WORK / "sol"
    if sol_dir.exists():
        shutil.rmtree(sol_dir)

    py = sys.executable
    run([py, str(UNPACK), str(PAIN_PPTX), str(BUILD)])
    run([py, str(UNPACK), str(SOL_PPTX), str(sol_dir)])

    media = BUILD / "ppt" / "media"

    # 1. copy solution media with prefix to avoid collisions
    media_map: dict[str, str] = {}
    for f in sorted((sol_dir / "ppt" / "media").iterdir()):
        new_name = f"s_{f.name}"
        shutil.copy(f, media / new_name)
        media_map[f"/ppt/media/{f.name}"] = f"/ppt/media/{new_name}"

    # 2. copy solution slide1/slide2 -> slide3/slide4 (+ remapped rels, drop notes)
    for src_n, dst_n in ((1, 3), (2, 4)):
        shutil.copy(sol_dir / "ppt" / "slides" / f"slide{src_n}.xml",
                    BUILD / "ppt" / "slides" / f"slide{dst_n}.xml")
        rels = (sol_dir / "ppt" / "slides" / "_rels" / f"slide{src_n}.xml.rels").read_text(encoding="utf-8")
        # remap image targets
        for old, new in media_map.items():
            rels = rels.replace(f'Target="{old}"', f'Target="{new}"')
        # drop notesSlide relationship line
        rels = re.sub(r'\s*<Relationship[^>]*notesSlide[^>]*/>', "", rels)
        (BUILD / "ppt" / "slides" / "_rels" / f"slide{dst_n}.xml.rels").write_text(rels, encoding="utf-8")

    # 3. logo for cover
    shutil.copy(LOGO, media / "logo.png")
    logo_rid = "Rlogo01"

    # 4. cover (slide5) + result (slide6)
    (BUILD / "ppt" / "slides" / "slide5.xml").write_text(build_cover(logo_rid), encoding="utf-8")
    (BUILD / "ppt" / "slides" / "slide6.xml").write_text(build_result(), encoding="utf-8")

    layout_rel = '<Relationship Type="%s" Target="/ppt/slideLayouts/slideLayout1.xml" Id="Rlay01"/>' % R_LAYOUT
    cover_rels = f'''<?xml version="1.0" encoding="utf-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  {layout_rel}
  <Relationship Type="{R_IMAGE}" Target="/ppt/media/logo.png" Id="{logo_rid}"/>
</Relationships>'''
    result_rels = f'''<?xml version="1.0" encoding="utf-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  {layout_rel}
</Relationships>'''
    (BUILD / "ppt" / "slides" / "_rels" / "slide5.xml.rels").write_text(cover_rels, encoding="utf-8")
    (BUILD / "ppt" / "slides" / "_rels" / "slide6.xml.rels").write_text(result_rels, encoding="utf-8")

    # 5. content types: add overrides for slide3..6
    ct_path = BUILD / "[Content_Types].xml"
    ct = ct_path.read_text(encoding="utf-8")
    add = ""
    for n in (3, 4, 5, 6):
        add += f'<Override PartName="/ppt/slides/slide{n}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
    ct = ct.replace("</Types>", add + "</Types>")
    ct_path.write_text(ct, encoding="utf-8")

    # 6. presentation.xml.rels: add slide rels
    pr_path = BUILD / "ppt" / "_rels" / "presentation.xml.rels"
    pr = pr_path.read_text(encoding="utf-8")
    add = ""
    for n, rid in ((3, "Rslide3"), (4, "Rslide4"), (5, "Rslide5"), (6, "Rslide6")):
        add += f'<Relationship Type="{R_SLIDE}" Target="/ppt/slides/slide{n}.xml" Id="{rid}"/>'
    pr = pr.replace("</Relationships>", add + "</Relationships>")
    pr_path.write_text(pr, encoding="utf-8")

    # 7. presentation.xml: rebuild sldIdLst in desired order
    pres_path = BUILD / "ppt" / "presentation.xml"
    pres = pres_path.read_text(encoding="utf-8")
    rns = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    # cover, pain1(R46a054108eaf42bb), pain2(R45864d47387c498b), sol1, sol2, result
    order = [
        (300, "Rslide5"),
        (256, "R46a054108eaf42bb"),
        (257, "R45864d47387c498b"),
        (301, "Rslide3"),
        (302, "Rslide4"),
        (303, "Rslide6"),
    ]
    items = "".join(f'<p:sldId {rns} id="{i}" r:id="{rid}"/>' for i, rid in order)
    pres = re.sub(r"<p:sldIdLst>.*?</p:sldIdLst>", f"<p:sldIdLst>{items}</p:sldIdLst>", pres, flags=re.DOTALL)
    pres_path.write_text(pres, encoding="utf-8")

    # 8. pack
    OUT_PPTX.parent.mkdir(parents=True, exist_ok=True)
    run([py, str(PACK), str(BUILD), str(OUT_PPTX)])
    print(f"Wrote {OUT_PPTX}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
