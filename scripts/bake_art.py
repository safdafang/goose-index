"""Render the art/*.svg textures and the paper and hedge edge masks into web/img/.

Needs playwright and pillow; uses Chrome from $CHROME or Playwright's Chromium.

    python scripts/bake_art.py
"""
import io
import os
import pathlib

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
ART, OUT = ROOT / "art", ROOT / "web" / "img"
SCALE = 2

# m: margin, b: slice width, p: middle slice length (the noise period); style.css uses the same m and b
PAPER = dict(m=32, b=56, p=280, radii=(3, 3, 3, 3), turb=(".055", 4, 7), disp=9)
HEDGE = dict(m=72, b=160, p=420, radii=(46, 38, 50, 40), turb=(".028", 3, 11), disp=30)
# name: (format, scale, colour to flatten onto, warp)
TEXTURES = {"paper": ("webp", 2, None, None), "wood-light": ("webp", 2, None, None), "wood-mid": ("webp", 2, None, None),
            "wood-dark": ("webp", 2, None, None), "stone": ("webp", 2, None, None), "hedge": ("webp", 2, None, HEDGE),
            "grass-c": ("webp", 1, "#9DC283", None), "grass-a": ("png", 2, None, None), "grass-b": ("png", 2, None, None)}
# (dy, blur, colour, opacity)
PAPER_SHADOW = [(2, 0, "rgb(120,100,60)", .22), (8, 12, "rgb(46,70,24)", .24)]
CARD_SHADOW = [(2, 0, "rgb(120,100,60)", .3), (10, 10, "rgb(15,40,15)", .4)]
HEDGE_SHADOW = [(10, 0, "#3A5F3D", 1), (18, 16, "rgb(46,70,24)", .3)]
# (dy, blur, colour, opacity)
HEDGE_SHADE = [(-18, 30, "rgb(20,45,20)", .45), (14, 22, "#fff", .06)]


def shape_path(s, m, radii):
    tl, tr, br, bl = radii
    a, z = m, s - m
    return (f"M{a + tl} {a}H{z - tr}A{tr} {tr} 0 0 1 {z} {a + tr}V{z - br}A{br} {br} 0 0 1 {z - br} {z}"
            f"H{a + bl}A{bl} {bl} 0 0 1 {a} {z - bl}V{a + tl}A{tl} {tl} 0 0 1 {a + tl} {a}Z")


def shadow_chain(layers):
    (dy1, r1, c1, o1), (dy2, r2, c2, o2) = layers
    first = (f'<feOffset in="d" dy="{dy1}" result="o1"/>' + (f'<feGaussianBlur in="o1" stdDeviation="{r1 / 2}" result="o1"/>' if r1 else "")
             + f'<feFlood flood-color="{c1}" flood-opacity="{o1}"/><feComposite in2="o1" operator="in" result="s1"/>')
    second = (f'<feMerge result="u"><feMergeNode in="s1"/><feMergeNode in="d"/></feMerge>'
              f'<feGaussianBlur in="u" stdDeviation="{r2 / 2}"/><feOffset dy="{dy2}" result="o2"/>'
              f'<feFlood flood-color="{c2}" flood-opacity="{o2}"/><feComposite in2="o2" operator="in" result="s2"/>')
    return first + second + '<feMerge><feMergeNode in="s2"/><feMergeNode in="s1"/></feMerge>'


def shade_chain(layers, disp):
    out, names = ['<feComponentTransfer in="SourceAlpha" result="inv"><feFuncA type="table" tableValues="1 0"/></feComponentTransfer>'], []
    for i, (dy, r, c, o) in enumerate(layers):
        out.append(f'<feOffset in="inv" dy="{dy}"/><feGaussianBlur stdDeviation="{r / 2}" result="b{i}"/>'
                   f'<feFlood flood-color="{c}" flood-opacity="{o}"/><feComposite in2="b{i}" operator="in"/>'
                   f'<feComposite in2="SourceAlpha" operator="in" result="h{i}"/>')
        names.append(f"h{i}")
    return ("".join(out) + '<feMerge result="h">' + "".join(f'<feMergeNode in="{n}"/>' for n in reversed(names)) + "</feMerge>"
            + f'<feDisplacementMap in="h" in2="n" scale="{disp}"/>')


def edge_svg(g, tail=""):
    m, b, p = g["m"], g["b"], g["p"]
    s = 2 * b + p
    freq, octaves, seed = g["turb"]
    return s, f"""<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 {s} {s}">
<filter id="f" filterUnits="userSpaceOnUse" x="0" y="0" width="{s}" height="{s}" color-interpolation-filters="sRGB">
<feTurbulence type="fractalNoise" baseFrequency="{freq}" numOctaves="{octaves}" seed="{seed}" stitchTiles="stitch" x="{b}" y="{b}" width="{p}" height="{p}" result="t"/>
<feTile in="t" result="n"/><feDisplacementMap in="SourceGraphic" in2="n" scale="{g['disp']}" result="d"/>{tail}</filter>
<path d="{shape_path(s, m, g['radii'])}" fill="#fff" filter="url(#f)"/></svg>"""


def warped(svg, w, h, g, k=3):
    """The texture tiled k x k and bent by the edge set's noise, made periodic over the k x k block."""
    inner = svg.split(">", 1)[1].rsplit("</svg>", 1)[0]
    W, H, pad = w * k, h * k, g["disp"]
    freq, octaves, seed = g["turb"]
    return W, H, f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<defs><pattern id="tex" width="{w}" height="{h}" patternUnits="userSpaceOnUse">{inner}</pattern></defs>
<filter id="w" filterUnits="userSpaceOnUse" x="{-pad}" y="{-pad}" width="{W + 2 * pad}" height="{H + 2 * pad}">
<feTurbulence type="fractalNoise" baseFrequency="{freq}" numOctaves="{octaves}" seed="{seed}" stitchTiles="stitch" x="0" y="0" width="{W}" height="{H}" result="t"/>
<feTile in="t" result="n"/><feDisplacementMap in="SourceGraphic" in2="n" scale="{g['disp']}"/></filter>
<rect x="{-pad}" y="{-pad}" width="{W + 2 * pad}" height="{H + 2 * pad}" fill="url(#tex)" filter="url(#w)"/></svg>"""


def shoot(pg, html, w, h):
    pg.set_viewport_size({"width": w, "height": h})
    pg.set_content(f'<html><body style="margin:0">{html}</body></html>')
    pg.wait_for_timeout(200)
    return Image.open(io.BytesIO(pg.screenshot(omit_background=True, clip={"x": 0, "y": 0, "width": w, "height": h})))


def save(img, name, fmt):
    path = OUT / f"{name}.{fmt}"
    if fmt == "webp":
        img.save(path, "WEBP", quality=92, method=6, alpha_quality=92)
    elif img.mode == "LA":
        img.save(path, "PNG", optimize=True)
    else:
        img.quantize(256, method=Image.Quantize.FASTOCTREE).save(path, "PNG", optimize=True)
    print(f"{path.relative_to(ROOT)}  {img.size[0]}x{img.size[1]}  {path.stat().st_size // 1024} KB")


def main():
    with sync_playwright() as pw:
        exe = os.environ.get("CHROME")
        browser = pw.chromium.launch(executable_path=exe) if exe else pw.chromium.launch()
        for name, (fmt, scale, base, warp) in TEXTURES.items():
            pg = browser.new_page(device_scale_factor=scale)
            svg = (ART / f"{name}.svg").read_text(encoding="utf-8")
            w = int(float(svg.split('width="', 1)[1].split('"', 1)[0]))
            h = int(float(svg.split('height="', 1)[1].split('"', 1)[0]))
            if warp:
                w, h, svg = warped(svg, w, h, warp)
            if base:
                svg = f'<div style="background:{base};width:{w}px;height:{h}px">{svg}</div>'
            img = shoot(pg, svg, w, h).convert("RGBA")
            opaque = img.getchannel("A").getextrema()[0] == 255
            save(img.convert("RGB") if opaque else img, name, fmt)
            pg.close()
        pg = browser.new_page(device_scale_factor=SCALE)
        for prefix, g, shadows in (("paper", PAPER, {"paper-shadow": PAPER_SHADOW, "card-shadow": CARD_SHADOW}),
                                   ("hedge", HEDGE, {"hedge-shadow": HEDGE_SHADOW})):
            s, svg = edge_svg(g)
            alpha = shoot(pg, svg, s, s).convert("RGBA").getchannel("A")
            save(Image.merge("LA", (Image.new("L", alpha.size, 255), alpha)), f"{prefix}-mask", "png")
            for name, layers in shadows.items():
                save(shoot(pg, edge_svg(g, shadow_chain(layers))[1], s, s).convert("RGBA"), name, "png")
            if prefix == "hedge":
                save(shoot(pg, edge_svg(g, shade_chain(HEDGE_SHADE, g["disp"]))[1], s, s).convert("RGBA"), "hedge-shade", "png")
        browser.close()


if __name__ == "__main__":
    main()
