"""Render the README banner, the logo and the social preview from art/brand.html.

They are drawn with the site's own textures and fonts, so they match it. Output, at 2x:

    .github/assets/banner.png   1280 x 400, the top of README.md
    .github/assets/logo.png     512 x 512, transparent
    .github/assets/social.png   1280 x 640, for Settings > Social preview (upload it by hand)

Dev-only: needs Playwright and Pillow (pip install playwright pillow). Uses Chrome from $CHROME, or
Playwright's own Chromium. Run: python scripts/bake_brand.py
"""
import io
import os
import pathlib

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC, OUT = ROOT / "art" / "brand.html", ROOT / ".github" / "assets"
SCALE = 2
# id: (output width in pixels, transparent)
SHOTS = {"banner": (1280 * SCALE, False), "logo": (512, True), "social": (1280, False)}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        chrome = os.environ.get("CHROME")
        browser = p.chromium.launch(executable_path=chrome) if chrome else p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 800}, device_scale_factor=SCALE)
        page.goto(SRC.as_uri())
        page.evaluate("document.fonts.ready")
        page.evaluate("document.body.style.background = 'transparent'")  # the grey is for previewing only
        page.wait_for_timeout(500)
        for name, (width, clear) in SHOTS.items():
            el = page.locator(f"#{name}")
            img = Image.open(io.BytesIO(el.screenshot(omit_background=clear)))
            if img.width != width:
                img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
            if not clear:
                img = img.convert("RGB")
            path = OUT / f"{name}.png"
            img.save(path, optimize=True)
            print(f"{path.relative_to(ROOT)}: {img.width}x{img.height}, {path.stat().st_size // 1024} kB")
        browser.close()


if __name__ == "__main__":
    main()
