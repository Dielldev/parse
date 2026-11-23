"""Render the model-stack loop.

  render.py stills OUT_DIR t1 t2 ...        PNG stills at those times (seconds)
  render.py video OUT.mp4 [--fps 30]        full loop -> mp4
"""
import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
SCALE = 1.5          # 1280x720 css px -> 1920x1080 frames


async def open_page(p):
    b = await p.chromium.launch(args=["--force-color-profile=srgb", "--disable-lcd-text"])
    pg = await b.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=SCALE)
    msgs = []
    pg.on("console", lambda m: msgs.append(m.text))
    pg.on("pageerror", lambda e: msgs.append("PAGEERROR " + str(e)))
    await pg.goto(f"file://{HERE}/index.html", wait_until="networkidle")
    await pg.evaluate("window.ready")
    ok = await pg.evaluate("""() => ['300 68px "Inter Tight"','400 20px "Inter Tight"','500 13px "IBM Plex Mono"'].map(f => document.fonts.check(f))""")
    print("fonts loaded:", ok, flush=True)
    for m in msgs:
        print("page:", m, flush=True)
    return b, pg


async def stills(out_dir, times):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        b, pg = await open_page(p)
        for t in times:
            await pg.evaluate(f"window.seek({t})")
            f = out / f"t{t:06.2f}.png"
            await pg.screenshot(path=str(f))
            print(f, flush=True)
        await b.close()


async def frames(fdir, fps):
    async with async_playwright() as p:
        b, pg = await open_page(p)
        meta = await pg.evaluate("window.__meta")
        total = int(round(meta["T"] * fps))
        for f in range(total):
            await pg.evaluate(f"window.seek({f / fps:.6f})")
            await pg.screenshot(path=str(Path(fdir) / f"f{f:05d}.png"))
            if f % 60 == 0:
                print(f"frame {f}/{total}", flush=True)
        await b.close()
    return total


def encode(fdir, fps, out):
    vf = "scale=in_range=full:out_range=tv:out_color_matrix=bt709:flags=lanczos+accurate_rnd+full_chroma_int,format=yuv420p"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-framerate", str(fps), "-i", str(Path(fdir) / "f%05d.png"),
           "-vf", vf, "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-profile:v", "high", "-an",
           "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
           "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "stills":
        asyncio.run(stills(sys.argv[2], [float(x) for x in sys.argv[3:]]))
    elif mode == "video":
        out = Path(sys.argv[2]).resolve()
        fps = 30
        if "--fps" in sys.argv:
            fps = int(sys.argv[sys.argv.index("--fps") + 1])
        fdir = tempfile.mkdtemp(prefix="models-frames-", dir=str(HERE))
        n = asyncio.run(frames(fdir, fps))
        encode(fdir, fps, out)
        print(f"video: {out} ({out.stat().st_size / 1e6:.2f} MB, {n} frames @ {fps} fps)")
