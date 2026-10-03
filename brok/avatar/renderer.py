"""Procedural robot renderer (Pillow only): one frame per (state, step). No image assets needed."""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from .states import AvatarState
from .themes import get_theme

W, H, SS = 240, 300, 2  # output size, supersample factor
FRAMES = 6


def render_frame(state: AvatarState, step: int = 0, theme: str = "cyan") -> Image.Image:
    c = get_theme(theme)
    img = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = lambda v: int(v * SS)  # noqa: E731
    ph = 2 * math.pi * (step % FRAMES) / FRAMES
    bob = (
        math.sin(ph) * 3
        if state in (AvatarState.IDLE, AvatarState.HAPPY, AvatarState.SPEAKING, AvatarState.SUCCESS)
        else 0
    )
    if state is AvatarState.SLEEPING:
        bob = math.sin(ph) * 1.5
    oy = bob

    def rr(box, r, fill, outline=None, w=0):
        d.rounded_rectangle(
            [s(box[0]), s(box[1] + oy), s(box[2]), s(box[3] + oy)], radius=s(r), fill=fill, outline=outline, width=s(w)
        )

    def ell(box, fill):
        d.ellipse([s(box[0]), s(box[1] + oy), s(box[2]), s(box[3] + oy)], fill=fill)

    def ln(pts, fill, w=3):
        d.line([(s(x), s(y + oy)) for x, y in pts], fill=fill, width=s(w), joint="curve")

    # body, legs, arms
    rr((70, 190, 170, 270), 18, c["body"], c["line"], 3)
    rr((92, 270, 112, 292), 6, c["panel"], c["line"], 2)
    rr((128, 270, 148, 292), 6, c["panel"], c["line"], 2)
    rr((92, 208, 148, 242), 8, c["panel"], c["line"], 2)
    core = c["error"] if state is AvatarState.ERROR else c["ok"] if state is AvatarState.SUCCESS else c["accent"]
    pulse = 6 + 2 * math.sin(ph)
    ell((120 - pulse, 225 - pulse, 120 + pulse, 225 + pulse), core)
    work = state in (AvatarState.TYPING, AvatarState.CODING, AvatarState.WORKING)
    wob = math.sin(ph * 2) * 10 if work else 0
    if state is AvatarState.HAPPY or state is AvatarState.SUCCESS:
        ln([(70, 205), (42, 170 - abs(math.sin(ph)) * 10)], c["body"], 10)
        ln([(170, 205), (198, 170 - abs(math.sin(ph + 1)) * 10)], c["body"], 10)
    elif state is AvatarState.NOTIFICATION:
        ln([(70, 205), (48, 238)], c["body"], 10)
        ln([(170, 205), (200, 160 + math.sin(ph * 2) * 8)], c["body"], 10)
    else:
        ln([(70, 205), (50, 245 - (wob if work else 0))], c["body"], 10)
        ln([(170, 205), (190, 245 + (wob if work else 0))], c["body"], 10)
    if state in (AvatarState.CODING, AvatarState.TYPING):  # tiny keyboard
        rr((60, 262, 180, 276), 4, c["panel"], c["line"], 2)
        for k in range(6):
            d.rectangle(
                [s(68 + k * 18), s(266 + oy), s(78 + k * 18), s(272 + oy)],
                fill=c["accent"] if (k + step) % 3 == 0 else c["body"],
            )
    # head + antenna
    tilt = 6 if state is AvatarState.CONFUSED else 0
    ln([(120, 52), (120 + tilt, 30)], c["line"], 4)
    tip = (
        c["warn"]
        if state in (AvatarState.NOTIFICATION, AvatarState.THINKING)
        else c["error"]
        if state is AvatarState.ERROR
        else c["glow"]
    )
    ell((112 + tilt, 20, 128 + tilt, 36), tip if (state is not AvatarState.THINKING or step % 2 == 0) else c["panel"])
    rr((50, 52, 190, 180), 28, c["body"], c["line"], 3)
    rr((64, 70, 176, 150), 18, c["panel"], c["line"], 2)
    ex, ey = (95, 145), 100
    col = c["error"] if state is AvatarState.ERROR else c["accent"]
    if state is AvatarState.SLEEPING:
        for x in ex:
            ln([(x - 12, ey), (x + 12, ey)], col, 4)
        d.text((s(170), s(40 + oy)), "z", fill=c["glow"])
    elif state is AvatarState.ERROR:
        for x in ex:
            ln([(x - 10, ey - 10), (x + 10, ey + 10)], col, 5)
            ln([(x - 10, ey + 10), (x + 10, ey - 10)], col, 5)
    elif state in (AvatarState.HAPPY, AvatarState.SUCCESS):
        for x in ex:
            ln([(x - 11, ey + 6), (x, ey - 8), (x + 11, ey + 6)], col, 5)
    elif state is AvatarState.CONFUSED:
        ell((ex[0] - 13, ey - 13, ex[0] + 13, ey + 13), col)
        ell((ex[1] - 7, ey - 7, ex[1] + 7, ey + 7), col)
    elif state is AvatarState.THINKING:
        for i, x in enumerate((105, 120, 135)):
            r = 5 + (3 if (step + i) % 3 == 0 else 0)
            ell((x - r, ey - r, x + r, ey + r), col)
    else:
        blink = state is AvatarState.IDLE and step == 4
        look = math.sin(ph) * 3 if state is AvatarState.LISTENING else 0
        for x in ex:
            if blink:
                ln([(x - 11, ey), (x + 11, ey)], col, 4)
            else:
                rr((x - 11 + look, ey - 13, x + 11 + look, ey + 13), 6, col)
    # mouth
    if state is AvatarState.SPEAKING:
        o = 4 + abs(math.sin(ph)) * 10
        rr((108, 128, 132, 128 + o), 4, c["line"])
    elif state is AvatarState.ERROR or state is AvatarState.CONFUSED:
        ln([(105, 135), (115, 128), (125, 135), (135, 128)], c["glow"], 3)
    elif state in (AvatarState.HAPPY, AvatarState.SUCCESS):
        ln([(105, 128), (120, 140), (135, 128)], c["glow"], 3)
    elif state is not AvatarState.SLEEPING:
        ln([(108, 134), (132, 134)], c["glow"], 3)
    if state is AvatarState.NOTIFICATION:
        ell((160, 8, 196, 44), c["warn"])
        d.text((s(174), s(18)), "!", fill=c["line"])
    return img.resize((W, H), Image.LANCZOS)


def render_state(state: AvatarState, theme: str = "cyan") -> list[Image.Image]:
    return [render_frame(state, i, theme) for i in range(FRAMES)]
