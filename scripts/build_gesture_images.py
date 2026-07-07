#!/usr/bin/env python3
"""Generate realistic hand-gesture reference PNGs for frontend/public/gestures/.

Most gestures use Google **Noto Emoji** color artwork (Apache-2.0) with a
medium-light skin tone (1f3fc) — realistic, gradient-shaded flat hands. Three
gestures have no Unicode emoji (three fingers, four fingers, the "L" sign); those
are drawn as a matching skin-gradient SVG so the whole set stays consistent.

Run:  .venv/bin/python scripts/build_gesture_images.py
(needs network for the Noto download, plus cairosvg + Pillow)
"""

from __future__ import annotations

import io
import urllib.request
from pathlib import Path

import cairosvg
from PIL import Image

OUT = Path(__file__).resolve().parents[1] / "frontend" / "public" / "gestures"
SIZE = 256
SKIN = "1f3fc"  # medium-light skin tone (warm beige)
NOTO = "https://raw.githubusercontent.com/googlefonts/noto-emoji/main/png/512"

# gesture id -> Noto base codepoint(s). Skin tone is appended automatically.
NOTO_MAP = {
    "one": "261d", "point": "261d",
    "two": "270c", "peace": "270c", "victory": "270c",
    "five": "270b", "open_palm": "270b", "stop": "270b",
    "high_five": "1f590",
    "fist": "270a",
    "thumb_up": "1f44d", "thumb_down": "1f44e",
    "ok": "1f44c", "small_ok": "1f44c",
    "pinch": "1f90f",
    "rock_on": "1f918",
    "call_me": "1f919",
    "i_love_you": "1f91f",
    "pinched_fingers": "1f90c",
    "crossed_fingers": "1f91e",
}
GAPS = ("three", "four", "l_shape")  # no Unicode emoji exists for these


def fetch_noto(codepoint: str) -> Image.Image:
    url = f"{NOTO}/emoji_u{codepoint}_{SKIN}.png"
    with urllib.request.urlopen(url, timeout=30) as resp:
        return Image.open(io.BytesIO(resp.read())).convert("RGBA")


def fit(img: Image.Image, size: int = SIZE, pad: float = 0.06) -> Image.Image:
    """Trim transparent margins, then center on a square with a little padding."""
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)
    inner = int(size * (1 - 2 * pad))
    img.thumbnail((inner, inner), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(img, ((size - img.width) // 2, (size - img.height) // 2), img)
    return canvas


# --- Custom skin-gradient hands for the 3 emoji-less gestures ------------------

GRAD = """
<defs>
  <linearGradient id="skin" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#F3CBA5"/><stop offset="1" stop-color="#DDA377"/>
  </linearGradient>
  <linearGradient id="skinDark" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#E6B389"/><stop offset="1" stop-color="#C98F63"/>
  </linearGradient>
</defs>
"""


def capsule(bx, by, angle, length, width, fill="url(#skin)"):
    x, y = bx - width / 2, by - length
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{length:.1f}" '
            f'rx="{width/2:.1f}" ry="{width/2:.1f}" transform="rotate({angle:.1f} {bx:.1f} {by:.1f})" '
            f'fill="{fill}"/>')


def fingers_hand(up: list[bool], thumb: str) -> str:
    """Palm-up hand; up = [index,middle,ring,pinky]; thumb: 'tuck'|'left'."""
    palm = ('<rect x="72" y="118" width="98" height="82" rx="34" ry="34" fill="url(#skin)"/>'
            '<rect x="72" y="150" width="98" height="50" rx="26" ry="26" fill="url(#skinDark)" opacity="0.35"/>')
    # spaced-out bases so individual fingers are clearly countable
    bases = [(88, 124, 19, 84), (111, 124, 20, 96), (134, 124, 19, 82), (154, 122, 16, 66)]
    folded, extended = [], []
    for (bx, by, w, ln), is_up in zip(bases, up):
        if is_up:
            extended.append(capsule(bx, by, 0, ln, w))
            # subtle inner shade down one side for depth (matches Noto's shading)
            extended.append(capsule(bx + w * 0.28, by, 0, ln - 6, w * 0.34, "url(#skinDark)"))
        else:
            folded.append(capsule(bx, by, 0, 34, w))
    th = capsule(84, 168, 78, 58, 26) if thumb == "tuck" else capsule(84, 160, -92, 66, 26)
    shadow = ('<ellipse cx="122" cy="210" rx="66" ry="12" fill="#000" opacity="0.10"/>')
    return GRAD + shadow + "".join(folded) + th + palm + "".join(extended)


def gap_svg(name: str) -> str:
    if name == "three":
        body = fingers_hand([True, True, True, False], "tuck")
    elif name == "four":
        body = fingers_hand([True, True, True, True], "tuck")
    else:  # l_shape: index up + thumb out to the side = an L
        body = fingers_hand([True, False, False, False], "left")
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 240">{body}</svg>'


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for gid, cp in NOTO_MAP.items():
        fit(fetch_noto(cp)).save(OUT / f"{gid}.png")
    for gid in GAPS:
        png = cairosvg.svg2png(bytestring=gap_svg(gid).encode(),
                               output_width=SIZE, output_height=SIZE,
                               background_color="rgba(0,0,0,0)")
        fit(Image.open(io.BytesIO(png)).convert("RGBA")).save(OUT / f"{gid}.png")
    total = len(NOTO_MAP) + len(GAPS)
    print(f"wrote {total} PNGs to {OUT}  (Noto Emoji: {len(NOTO_MAP)}, custom: {len(GAPS)})")


if __name__ == "__main__":
    main()
