"""Render stills of the film at chosen times, plus a labelled contact sheet, for review.

  .venv/bin/python video/tools/stills.py OUT_DIR 0.5 1.2 3.4 ...      # explicit times (seconds)
  .venv/bin/python video/tools/stills.py OUT_DIR --every 0.5           # one still per beat
  .venv/bin/python video/tools/stills.py OUT_DIR --strip 9.8 10.4      # every frame in a range (60 fps)
  .venv/bin/python video/tools/stills.py OUT_DIR --src video/agentic --every 0.5   # another film folder
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).parent))
from serve import serve  # noqa: E402


async def shoot(out: Path, times: list[float], src: str | None = None) -> list[Path]:
    base, httpd = serve(src)
    paths = []
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        await pg.goto(base + "/index.html", wait_until="networkidle")
        info = await pg.evaluate("window.ready")
        print("ready", info, flush=True)
        for t in times:
            await pg.evaluate(f"window.seek({t})")
            f = out / f"t{t:07.3f}.png"
            await pg.screenshot(path=str(f))
            paths.append(f)
        if errors:
            print("PAGE ERRORS:", *errors[:12], sep="\n  ")
        await b.close()
    httpd.shutdown()
    return paths


def sheet(paths: list[Path], out: Path, cols: int = 4, w: int = 480) -> Path:
    h = int(w * 9 / 16)
    rows = (len(paths) + cols - 1) // cols
    im = Image.new("RGB", (cols * w, rows * (h + 26)), (20, 20, 22))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 16)
    except OSError:
        font = ImageFont.load_default()
    for i, p in enumerate(paths):
        x, y = (i % cols) * w, (i // cols) * (h + 26)
        im.paste(Image.open(p).convert("RGB").resize((w, h), Image.LANCZOS), (x, y + 26))
        d.text((x + 6, y + 4), p.stem[1:] + " s", fill=(230, 230, 230), font=font)
    f = out / "sheet.png"
    im.save(f)
    return f


def main():
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    args = sys.argv[2:]
    src = None
    if args and args[0] == "--src":
        src, args = args[1], args[2:]
    if args and args[0] == "--every":
        step = float(args[1]); times = [round(i * step, 3) for i in range(int(30 / step))]
    elif args and args[0] == "--strip":
        a, b = float(args[1]), float(args[2]); times = [round(a + i / 60, 4) for i in range(int((b - a) * 60) + 1)]
    else:
        times = [float(x) for x in args]
    paths = asyncio.run(shoot(out, times, src))
    print("sheet", sheet(paths, out, cols=6 if len(paths) > 24 else 4))


if __name__ == "__main__":
    main()
