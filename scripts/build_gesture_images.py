#!/usr/bin/env python3
"""Generate hand-gesture reference PNGs for frontend/public/gestures/.

Parametric capsule-style hand (palm + 5 digits). Each gesture specifies which
digits are extended (and the thumb's direction), so finger counts are exactly
right. Rendered as SVG then rasterized to transparent PNG via cairosvg.

Run:  .venv/bin/python scripts/build_gesture_images.py
"""

from __future__ import annotations

import math
from pathlib import Path

import cairosvg

OUT = Path(__file__).resolve().parents[1] / "frontend" / "public" / "gestures"
SIZE = 256
VB = 240  # viewBox units

SKIN = "#F6C79E"
EDGE = "#C8895B"
SW = 5  # stroke width

# Digit anchor points on the palm (base of each finger / thumb) and up-length.
PALM = dict(x=72, y=120, w=96, h=78, rx=30)
FINGERS = {
    # name: (base_x, base_y, width, up_length, tallness_bias)
    "index":  (89, 126, 21, 80),
    "middle": (111, 126, 22, 92),
    "ring":   (133, 126, 21, 78),
    "pinky":  (153, 124, 18, 62),
}
THUMB_BASE = (78, 168)
THUMB_W = 24


def capsule(bx: float, by: float, angle_deg: float, length: float, width: float) -> str:
    """A stadium/capsule whose base-center is (bx,by), pointing 'up' then rotated
    by angle_deg (0 = straight up, + = clockwise)."""
    x = bx - width / 2
    y = by - length
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{length:.1f}" '
        f'rx="{width/2:.1f}" ry="{width/2:.1f}" '
        f'transform="rotate({angle_deg:.1f} {bx:.1f} {by:.1f})" '
        f'fill="{SKIN}" stroke="{EDGE}" stroke-width="{SW}"/>'
    )


def finger(name: str, extended: bool, angle: float = 0.0) -> str:
    bx, by, w, up = FINGERS[name]
    length = up if extended else 34  # folded = short knuckle stub
    return capsule(bx, by, angle, length, w)


def palm() -> str:
    p = PALM
    return (
        f'<rect x="{p["x"]}" y="{p["y"]}" width="{p["w"]}" height="{p["h"]}" '
        f'rx="{p["rx"]}" ry="{p["rx"]}" fill="{SKIN}" stroke="{EDGE}" stroke-width="{SW}"/>'
    )


def thumb(mode: str) -> str:
    bx, by = THUMB_BASE
    if mode == "across":     # tucked across the fist
        return capsule(bx + 12, by - 6, 78, 60, THUMB_W)
    if mode == "side":       # extended out to the upper-left (open hand)
        return capsule(bx, by, -52, 74, THUMB_W)
    if mode == "up":         # straight up (thumbs-up)
        return capsule(bx - 2, by, -6, 86, THUMB_W)
    if mode == "down":       # straight down (thumbs-down)
        return capsule(bx - 2, by - 40, 186, 86, THUMB_W)
    if mode == "left":       # horizontal, pointing left (L shape)
        return capsule(bx, by - 8, -92, 66, THUMB_W)
    return ""  # hidden/tucked


def ring(cx: float, cy: float, r: float) -> str:
    return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
            f'stroke="{SKIN}" stroke-width="{THUMB_W}"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
            f'stroke="{EDGE}" stroke-width="{SW}" opacity="0.9"/>')


def knuckle_row(cx: float, y: float, total_w: float, n: int = 4) -> str:
    step = total_w / n
    x0 = cx - total_w / 2 + step / 2
    r = step * 0.44
    return "".join(
        f'<circle cx="{x0 + i*step:.1f}" cy="{y:.1f}" r="{r:.1f}" '
        f'fill="{SKIN}" stroke="{EDGE}" stroke-width="{SW}"/>'
        for i in range(n)
    )


def thumbs(direction: str) -> str:
    """Sideways fist with the thumb clearly pointing up or down."""
    up = direction == "up"
    if up:
        fist = f'<rect x="80" y="118" width="92" height="82" rx="30" ry="30" fill="{SKIN}" stroke="{EDGE}" stroke-width="{SW}"/>'
        knuck = knuckle_row(126, 120, 74)          # knuckles along the top
        th = capsule(84, 186, -8, 124, 28)         # thumb up the left side
        return svg_wrap(knuck + fist + th)
    fist = f'<rect x="80" y="40" width="92" height="82" rx="30" ry="30" fill="{SKIN}" stroke="{EDGE}" stroke-width="{SW}"/>'
    knuck = knuckle_row(126, 120, 74)              # knuckles along the bottom
    th = capsule(84, 54, 188, 124, 28)             # thumb down the left side
    return svg_wrap(fist + knuck + th)


def svg_wrap(body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VB} {VB}">'
        f'<g stroke-linejoin="round">{body}</g></svg>'
    )


def base_hand(index=False, middle=False, ring_=False, pinky=False, thumb_mode="across",
              finger_angles=None) -> str:
    """Palm-up hand with the given fingers extended and thumb mode."""
    fa = finger_angles or {}
    order = []
    # Draw folded fingers first (behind), then thumb, then extended fingers on top.
    for n, ext in (("index", index), ("middle", middle), ("ring", ring_), ("pinky", pinky)):
        if not ext:
            order.append(finger(n, False, fa.get(n, 0)))
    order.append(thumb(thumb_mode))
    order.append(palm())
    for n, ext in (("index", index), ("middle", middle), ("ring", ring_), ("pinky", pinky)):
        if ext:
            order.append(finger(n, True, fa.get(n, 0)))
    return "".join(order)


def gesture_svg(name: str) -> str:
    F = dict  # readability
    if name in ("one", "point"):
        return svg_wrap(base_hand(index=True))
    if name in ("two", "peace", "victory"):
        return svg_wrap(base_hand(index=True, middle=True))
    if name == "three":
        return svg_wrap(base_hand(index=True, middle=True, ring_=True))
    if name == "four":
        return svg_wrap(base_hand(index=True, middle=True, ring_=True, pinky=True))
    if name in ("five", "open_palm", "high_five", "stop"):
        return svg_wrap(base_hand(index=True, middle=True, ring_=True, pinky=True, thumb_mode="side"))
    if name == "fist":
        return svg_wrap(base_hand(thumb_mode="across"))
    if name == "thumb_up":
        return thumbs("up")
    if name == "thumb_down":
        return thumbs("down")
    if name == "rock_on":
        return svg_wrap(base_hand(index=True, pinky=True, thumb_mode="across"))
    if name == "call_me":
        return svg_wrap(base_hand(pinky=True, thumb_mode="side"))
    if name == "i_love_you":
        return svg_wrap(base_hand(index=True, pinky=True, thumb_mode="side"))
    if name == "l_shape":
        return svg_wrap(base_hand(index=True, thumb_mode="left"))
    if name == "crossed_fingers":
        # index and middle up, crossed near the tips
        return svg_wrap(base_hand(index=True, middle=True, finger_angles={"index": 12, "middle": -8}))
    if name in ("ok", "small_ok"):
        # middle+ring+pinky up; thumb+index form a ring at the upper-left
        body = base_hand(middle=True, ring_=True, pinky=True, thumb_mode=None)
        body += ring(92, 96, 22)
        return svg_wrap(body)
    if name == "pinch":
        # thumb + index tips meeting; middle/ring/pinky up
        body = base_hand(middle=True, ring_=True, pinky=True, thumb_mode=None)
        body += capsule(96, 150, -18, 66, 20)   # index angled toward tip
        body += capsule(84, 168, -40, 70, THUMB_W)  # thumb angled toward tip
        return svg_wrap(body)
    if name == "pinched_fingers":
        # all fingertips converge upward to a point (~120,58)
        body = [palm()]
        # angle each finger INWARD so the tips converge to a point near the top
        for n, ang in (("index", 26), ("middle", 9), ("ring", -9), ("pinky", -24)):
            body.append(finger(n, True, ang))
        body.append(capsule(*THUMB_BASE, 18, 78, THUMB_W))  # thumb converging too
        return svg_wrap("".join(body))
    raise ValueError(f"unknown gesture {name}")


GESTURES = [
    "one", "two", "three", "four", "five", "point", "peace", "victory",
    "open_palm", "high_five", "stop", "fist", "thumb_up", "ok", "pinch",
    "small_ok", "rock_on", "call_me", "thumb_down", "i_love_you", "l_shape",
    "pinched_fingers", "crossed_fingers",
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name in GESTURES:
        svg = gesture_svg(name)
        cairosvg.svg2png(bytestring=svg.encode(), write_to=str(OUT / f"{name}.png"),
                         output_width=SIZE, output_height=SIZE, background_color="rgba(0,0,0,0)")
    print(f"wrote {len(GESTURES)} PNGs to {OUT}")


if __name__ == "__main__":
    main()
