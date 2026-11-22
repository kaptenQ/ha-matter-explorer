"""Render the brand PNGs from the SVGs in this directory.

Usage: /tmp/pwenv/bin/python scripts/brand/render.py scripts/brand custom_components/matter_explorer/brand \
           docs/screenshots/0190-icons.png
(needs playwright + pillow; set CHROMIUM to a chromium binary if the bundled one is missing)
"""

import os
import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright


def render(svg: Path, scale: int, tmp: Path) -> Image.Image:
    """Render an SVG at `scale`x with a transparent background, trimmed to its content."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM"))
        page = browser.new_page(device_scale_factor=scale)
        page.set_content(f"<body style='margin:0'>{svg.read_text()}</body>")
        page.locator("svg").screenshot(path=str(tmp), omit_background=True)
        browser.close()
    im = Image.open(tmp).convert("RGBA")
    return im.crop(im.getbbox())


def square(im: Image.Image, size: int) -> Image.Image:
    side = max(im.size)
    canvas = Image.new("RGBA", (side, side))
    canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def save_logo(im: Image.Image, out: Path, name: str) -> None:
    for suffix, height in (("", 128), ("@2x", 256)):
        width = round(im.width * height / im.height)
        im.resize((width, height), Image.Resampling.LANCZOS).save(
            out / f"{name}{suffix}.png", optimize=True
        )


def main() -> None:
    src, out, preview = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / ".render.png"
    icon = render(src / "icon.svg", 4, tmp)
    square(icon, 256).save(out / "icon.png", optimize=True)
    square(icon, 512).save(out / "icon@2x.png", optimize=True)
    save_logo(render(src / "logo.svg", 4, tmp), out, "logo")
    save_logo(render(src / "dark_logo.svg", 4, tmp), out, "dark_logo")
    tmp.unlink()
    # Preview: icon at 32/64/256 px and the logos, on a light and a dark background.
    sheet = Image.new("RGBA", (1500, 760), (128, 128, 128, 255))
    for row, (bg, logo) in enumerate(
        (((255, 255, 255, 255), "logo"), ((28, 28, 28, 255), "dark_logo"))
    ):
        panel = Image.new("RGBA", (1480, 365), bg)
        x = 10
        for size in (32, 64, 256):
            panel.alpha_composite(
                Image.open(out / "icon.png").resize((size, size), Image.Resampling.LANCZOS), (x, 10)
            )
            x += size + 20
        panel.alpha_composite(Image.open(out / f"{logo}.png"), (x, 10))
        sheet.alpha_composite(panel, (10, 10 + row * 375))
    sheet.save(preview)


if __name__ == "__main__":
    main()
