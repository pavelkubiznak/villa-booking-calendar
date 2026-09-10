#!/usr/bin/env python3
"""Vygeneruje ikony pro přidání kalendáře na plochu (iOS/Android).

Kreslí se vektorově v Pillow do 4x zvětšeného plátna a pak zmenší (antialiasing).
Spouští se ručně, výstup se commituje do icons/ — v běhu webu se nepoužívá.
"""
import os
from PIL import Image, ImageDraw

OUT = os.path.dirname(os.path.abspath(__file__))

# (název, barva pozadí nahoře, dole, barva záhlaví kalendáře, barva zvýrazněných dnů)
THEMES = {
    "icon":       ("#1E6FD9", "#0D47A1", "#0B3C8A", "#1565C0"),  # úklidový kalendář (modrá)
    "owner-icon": ("#D2A32B", "#8A6508", "#6F5107", "#B8860B"),  # majitel (zlatá)
}

DAY_BG = "#CBD6E2"   # neobsazený den
CARD   = "#FFFFFF"

S = 1024          # cílová hrana
K = 4             # supersampling


def hexrgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def draw_icon(top, bottom, header, accent):
    n = S * K
    img = Image.new("RGB", (n, n))
    d = ImageDraw.Draw(img)

    # pozadí — svislý přechod
    c0, c1 = hexrgb(top), hexrgb(bottom)
    for y in range(n):
        d.line([(0, y), (n, y)], fill=lerp(c0, c1, y / (n - 1)))

    def px(v):
        return round(v * n)

    def rr(x0, y0, x1, y1, r, fill):
        d.rounded_rectangle([px(x0), px(y0), px(x1), px(y1)], radius=px(r), fill=fill)

    # kroužky vazby nad kartou
    for cx in (0.335, 0.665):
        rr(cx - 0.028, 0.150, cx + 0.028, 0.280, 0.028, CARD)

    # tělo kalendáře
    rr(0.150, 0.215, 0.850, 0.845, 0.070, CARD)
    # záhlaví (nahoře zaoblené, dole rovné — dvě překryté kresby)
    rr(0.150, 0.215, 0.850, 0.330, 0.070, hexrgb(header))
    d.rectangle([px(0.150), px(0.250), px(0.850), px(0.375)], fill=hexrgb(header))

    # mřížka dnů 4x3; jeden souvislý pobyt zvýrazněný barvou platformy
    cols, rows = 4, 3
    x0, x1, y0, y1 = 0.215, 0.785, 0.435, 0.795
    cw, ch = (x1 - x0) / cols, (y1 - y0) / rows
    dw, dh = cw * 0.62, ch * 0.55
    booked = {(1, 1), (1, 2), (1, 3), (2, 0)}   # (řádek, sloupec)
    for r in range(rows):
        for c in range(cols):
            cx = x0 + cw * (c + 0.5)
            cy = y0 + ch * (r + 0.5)
            fill = hexrgb(accent) if (r, c) in booked else hexrgb(DAY_BG)
            rr(cx - dw / 2, cy - dh / 2, cx + dw / 2, cy + dh / 2, dw * 0.30, fill)

    return img.resize((S, S), Image.LANCZOS)


os.makedirs(OUT, exist_ok=True)
SIZES = [180, 192, 512, 32]
for name, (top, bottom, header, accent) in THEMES.items():
    base = draw_icon(top, bottom, header, accent)
    for s in SIZES:
        base.resize((s, s), Image.LANCZOS).save(
            os.path.join(OUT, f"{name}-{s}.png"), optimize=True)
print("hotovo:", sorted(os.listdir(OUT)))
