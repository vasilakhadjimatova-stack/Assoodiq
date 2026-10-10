"""Assoodiq logotipini vektor (SVG) ko'rinishda yaratish.

    python scripts/make_logo.py Montserrat-SemiBold.ttf static/img templates/partials/wordmark.svg

Yozuv Montserrat 600 harflaridan, A va Q urg'ulari qo'lda chiziladi.
"""
import math
import sys
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.boundsPen import BoundsPen

FONT = sys.argv[1]
OUT = sys.argv[2]
f = TTFont(FONT)
gs = f.getGlyphSet()
cmap = f.getBestCmap()
hmtx = f["hmtx"]

def glyph(ch):
    name = cmap[ord(ch)]
    pen = SVGPathPen(gs)
    gs[name].draw(pen)
    bp = BoundsPen(gs); gs[name].draw(bp)
    return pen.getCommands(), hmtx[name][0], bp.bounds

CAP = 700
_, _, ib = glyph("I")
STEM = ib[2] - ib[0]             # shrift ustuni qalinligi
TRACK = 28

DARK, MID, GREEN, LIGHT = "#065A47", "#188B63", "#3CB885", "#78D1AB"

def wordmark(text_color, a_accent, q_accent):
    parts = []
    x = 0
    # A: ko'ndalang chiziqsiz Λ + ochiq kitob shaklidagi urg'u
    aw = 690
    s = STEM
    apex = aw / 2
    left = f"M{0},{0} L{apex - s*0.62},{CAP} L{apex + s*0.62},{CAP} L{s*1.15},{0} Z"
    right = f"M{aw},{0} L{apex + s*0.62},{CAP} L{apex - s*0.05},{CAP - s*1.25} L{aw - s*1.15},{0} Z"
    parts.append(f'<path fill="{text_color}" d="{left} {right}"/>')
    # kitob: ikki varaq, o'rtada pastga egilgan
    by = 230
    book = (f"M{-40},{by + 70} C{80},{by + 150} {200},{by + 130} {apex},{by - 30} "
            f"C{aw - 200},{by + 130} {aw - 80},{by + 150} {aw + 40},{by + 70} "
            f"L{aw + 40},{by - 15} C{aw - 80},{by + 60} {aw - 200},{by + 40} {apex},{by - 120} "
            f"C{200},{by + 40} {80},{by + 60} {-40},{by - 15} Z")
    parts.append(f'<path fill="{a_accent}" d="{book}"/>')
    x += aw + TRACK
    for ch in "SSOODI":
        d, adv, _ = glyph(ch)
        parts.append(f'<path fill="{text_color}" transform="translate({x},0)" d="{d}"/>')
        x += adv + TRACK
    d, adv, b = glyph("O")
    parts.append(f'<path fill="{text_color}" transform="translate({x},0)" d="{d}"/>')
    # Q dumi: O ichidan pastga-o'ngga chiquvchi yashil chiziq
    cx = x + (b[0] + b[2]) / 2
    ox, oy = x + b[2], b[1]
    t = STEM * 0.95
    x1, y1 = cx + 70, 190
    x2, y2 = ox + 30, oy - 45
    ang = math.atan2(y2 - y1, x2 - x1)
    nx, ny = -math.sin(ang) * t / 2, math.cos(ang) * t / 2
    tail = f"M{x1+nx},{y1+ny} L{x2+nx},{y2+ny} L{x2-nx},{y2-ny} L{x1-nx},{y1-ny} Z"
    parts.append(f'<path fill="{q_accent}" d="{tail}"/>')
    x += adv
    width = x + 60
    return parts, width

def svg_wordmark(text_color, a_accent, q_accent):
    parts, width = wordmark(text_color, a_accent, q_accent)
    top, bottom = CAP + 40, -130
    h = top - bottom
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-60 0 {width + 60:.0f} {h}" role="img" aria-label="Assoodiq">'
            f'<g transform="translate(0,{top}) scale(1,-1)">' + "".join(parts) + "</g></svg>")

# Belgi: uchta chorak doira tashqi burchakdan chiziladi — orasida to'rt qirrali
# yulduz ochiq qoladi; to'rtinchi (to'q) bo'lak markazdan chizilgan chorak doira.
def quarter(cx, cy, color):
    # markazi (cx,cy) burchakda, radiusi 24, kvadrat ichidagi chorak doira
    sx = 24 if cx == 0 else -24
    sy = 24 if cy == 0 else -24
    sweep = 1 if (sx > 0) == (sy > 0) else 0
    return f'<path fill="{color}" d="M{cx},{cy}H{cx+sx}A24,24 0 0 {sweep} {cx},{cy+sy}Z"/>'

mark = (quarter(0, 0, GREEN) + quarter(48, 0, LIGHT) + quarter(0, 48, MID)
        + f'<path fill="{DARK}" d="M24,24H48A24,24 0 0 1 24,48Z"/>')
mark_svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" role="img" aria-label="Assoodiq">{mark}</svg>'

open(f"{OUT}/mark.svg", "w").write(mark_svg)
open(f"{OUT}/wordmark.svg", "w").write(svg_wordmark(DARK, LIGHT, GREEN))
open(f"{OUT}/wordmark-light.svg", "w").write(svg_wordmark("#F2F7F4", LIGHT, GREEN))
# Ilova ikonkasi: oq plitka ustida belgi (favicon, telefon ekrani)
icon = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#FFFFFF"/>'
        f'<g transform="translate(10 10) scale(0.9166)">{mark}</g></svg>')
open(f"{OUT}/favicon.svg", "w").write(icon)
print("ok", STEM)

# Shablonga to'g'ridan-to'g'ri qo'yiladigan variant: ranglar CSS'dan (mavzuga moslashadi)
inline = svg_wordmark("TXT", "AC1", "AC2")
inline = (inline.replace('xmlns="http://www.w3.org/2000/svg" ', 'class="wordmark" ')
          .replace('fill="TXT"', 'class="wm-t"').replace('fill="AC1"', 'class="wm-a1"')
          .replace('fill="AC2"', 'class="wm-a2"'))
open(sys.argv[3], "w").write(inline)
