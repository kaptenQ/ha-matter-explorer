"""Render the brand PNGs: /tmp/pwenv/bin/python scripts/brand/render.py scripts/brand custom_components/matter_explorer/brand docs/screenshots/0190-icons.png"""
import sys, pathlib
from playwright.sync_api import sync_playwright
from PIL import Image
src, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
def render(svg, scale, path):
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=__import__("glob").glob("/home/dev/.cache/ms-playwright/chromium_headless_shell-1255/*/chrome-headless-shell")[0]); p = b.new_page(device_scale_factor=scale)
        p.set_content(f"<body style='margin:0'>{svg.read_text()}</body>")
        p.locator("svg").screenshot(path=str(path), omit_background=True); b.close()
    im = Image.open(path).convert("RGBA"); return im.crop(im.getbbox())
def fit_square(im, n):
    w, h = im.size; s = max(w, h); c = Image.new("RGBA", (s, s)); c.paste(im, ((s-w)//2, (s-h)//2))
    return c.resize((n, n), Image.LANCZOS)
out.mkdir(parents=True, exist_ok=True)
ic = render(src/"icon.svg", 4, "/tmp/brand/i.png")
fit_square(ic, 256).save(out/"icon.png", optimize=True); fit_square(ic, 512).save(out/"icon@2x.png", optimize=True)
lg = render(src/"logo.svg", 4, "/tmp/brand/l.png")
for n, h in (("logo.png", 128), ("logo@2x.png", 256)):
    w = round(lg.width * h / lg.height); lg.resize((w, h), Image.LANCZOS).save(out/n, optimize=True)
# preview
bgs = [(255,255,255,255), (28,28,28,255)]
pv = Image.new("RGBA", (1500, 760), (128,128,128,255)); x = 10
for i, bg in enumerate(bgs):
    y = 10 + i*375; panel = Image.new("RGBA", (1480, 365), bg); px = 10
    for n in (32, 64, 256):
        t = Image.open(out/"icon.png").resize((n, n), Image.LANCZOS); panel.alpha_composite(t, (px, 10)); px += n + 20
    l = Image.open(out/"logo.png"); panel.alpha_composite(l, (px, 10))
    pv.alpha_composite(panel, (10, y))
pv.save(sys.argv[3])
dl = render(src/"dark_logo.svg", 4, "/tmp/brand/d.png")
for n, h in (("dark_logo.png", 128), ("dark_logo@2x.png", 256)):
    w = round(dl.width * h / dl.height); dl.resize((w, h), Image.LANCZOS).save(out/n, optimize=True)
pv = Image.open(sys.argv[3]); pv.alpha_composite(Image.open(out/"dark_logo.png"), (920, 395)); pv.save(sys.argv[3])
