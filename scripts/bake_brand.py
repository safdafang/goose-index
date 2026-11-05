"""Render the banner, logo and social preview from art/brand.html into .github/assets/.

Needs playwright and pillow; uses Chrome from $CHROME or Playwright's Chromium.

    python scripts/bake_brand.py
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
        page.evaluate("document.body.style.background = 'transparent'")
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
