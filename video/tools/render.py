"""Render the Parse film to MP4: frames from window.seek(t) in headless Chromium, sound from audio.js, ffmpeg to encode.

  .venv/bin/python video/tools/render.py                    # final: 1920x1080, 60 fps, 3-sample motion blur
  .venv/bin/python video/tools/render.py --draft            # quick look: 30 fps, no blur
  .venv/bin/python video/tools/render.py --workers 6 --out video/out/parse-showcase.mp4
  .venv/bin/python video/tools/render.py --src video/agentic --out video/out/parse-agentic-loop.mp4

Motion blur: each frame averages `--sub` samples spread over a 180° shutter (half a frame), centred on the frame time.
Frames go to a scratch directory (--frames, default: a temp dir) and are deleted only if you pass --clean.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import multiprocessing as mp
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).parent))
from serve import serve  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
VIEW = {"width": 1920, "height": 1080}


async def _open(p, base, wid=0):
    await asyncio.sleep(wid * 0.7)                            # stagger workers so the page loads don't pile up
    b = await p.chromium.launch(args=["--force-color-profile=srgb", "--disable-lcd-text"])
    pg = await b.new_page(viewport=VIEW, device_scale_factor=1)
    for attempt in range(5):
        try:
            await pg.goto(base + "/index.html", wait_until="networkidle")
            await pg.evaluate("window.ready")          # rejects if a stylesheet or font did not load
            return b, pg
        except Exception as e:  # noqa: BLE001 - a busy local server or a dropped asset: load the page again
            if attempt == 4:
                raise
            print(f"  page not ready ({str(e).splitlines()[0][:120]}), reloading", flush=True)
            await asyncio.sleep(1.5)
    return b, pg


async def _frames(base: str, frames: list[int], fps: int, sub: int, outdir: str, wid: int):
    async with async_playwright() as p:
        b, pg = await _open(p, base, wid)
        cdp = await pg.context.new_cdp_session(pg)
        shutter = 0.5 / fps                                   # 180 degrees
        offs = [0.0] if sub <= 1 else [(-0.5 + k / (sub - 1)) * shutter for k in range(sub)]
        t0 = time.time()
        for n, f in enumerate(frames):
            acc = None
            for o in offs:
                t = max(0.0, f / fps + o)
                await pg.evaluate(f"window.seek({t:.6f})")
                r = await cdp.send("Page.captureScreenshot", {"format": "png", "optimizeForSpeed": True})
                a = np.asarray(Image.open(io.BytesIO(base64.b64decode(r["data"]))).convert("RGB"), dtype=np.uint16)
                acc = a if acc is None else acc + a
            img = (acc / len(offs) + 0.5).astype(np.uint8) if len(offs) > 1 else acc.astype(np.uint8)
            Image.fromarray(img).save(os.path.join(outdir, f"f{f:05d}.png"), compress_level=1)
            if n % 60 == 0:
                print(f"  worker {wid}: {n + 1}/{len(frames)} frames, {time.time() - t0:.0f}s", flush=True)
        await b.close()


def _worker(args):
    base, frames, fps, sub, outdir, wid = args
    asyncio.run(_frames(base, frames, fps, sub, outdir, wid))


async def _audio(base: str, wav: Path) -> float:
    async with async_playwright() as p:
        b, pg = await _open(p, base)
        n = await pg.evaluate("window.renderAudio()")
        chunks = []
        for i in range(0, n, 1 << 20):
            chunks.append(await pg.evaluate(f"window.__wav.slice({i}, {i + (1 << 20)})"))
        peak = await pg.evaluate("window.__peak")
        await b.close()
    wav.write_bytes(base64.b64decode("".join(chunks)))
    return peak


def loudnorm(src: Path, dst: Path) -> dict:
    """Two-pass EBU R128 to -14 LUFS, true peak -1 dBTP."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-af",
                        "loudnorm=I=-14:TP=-1.0:LRA=11:print_format=json", "-f", "null", "-"], capture_output=True, text=True)
    m = json.loads(r.stderr[r.stderr.rindex("{"):r.stderr.rindex("}") + 1])
    af = (f"loudnorm=I=-14:TP=-1.0:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-af", af, "-ar", "48000",
                    "-c:a", "pcm_s24le", str(dst)], check=True)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "video" / "out" / "parse-showcase.mp4"))
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--sub", type=int, default=3)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--frames", default="")
    ap.add_argument("--draft", action="store_true")
    ap.add_argument("--clean", action="store_true")
    ap.add_argument("--duration", type=float, default=30.0)
    ap.add_argument("--src", default="", help="film folder to serve (default video/src)")
    a = ap.parse_args()
    if a.draft:
        a.fps, a.sub = 30, 1
    out = Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    fdir = Path(a.frames or tempfile.mkdtemp(prefix="parse-frames-"))
    fdir.mkdir(parents=True, exist_ok=True)
    base, httpd = serve(a.src or None)
    t0 = time.time()

    print("sound: rendering", flush=True)
    raw = out.with_suffix(".raw.wav")
    peak = asyncio.run(_audio(base, raw))
    wav = out.with_suffix(".wav")
    m = loudnorm(raw, wav)
    raw.unlink()
    print(f"sound: peak before mastering {peak:.3f}; measured {m['input_i']} LUFS, TP {m['input_tp']} dBTP → -14 LUFS", flush=True)

    total = int(round(a.duration * a.fps))
    todo = [f for f in range(total) if not (fdir / f"f{f:05d}.png").exists()]
    print(f"frames: {total} at {a.fps} fps, {a.sub} samples each, {len(todo)} to render with {a.workers} workers → {fdir}", flush=True)
    if todo:
        parts = [todo[i::a.workers] for i in range(a.workers)]
        with mp.get_context("spawn").Pool(a.workers) as pool:
            pool.map(_worker, [(base, part, a.fps, a.sub, str(fdir), i) for i, part in enumerate(parts) if part])
    httpd.shutdown()
    print(f"frames: done in {time.time() - t0:.0f}s", flush=True)

    vf = "scale=in_range=full:out_range=tv:out_color_matrix=bt709:flags=lanczos+accurate_rnd+full_chroma_int,format=yuv420p"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-framerate", str(a.fps), "-i", str(fdir / "f%05d.png"),
           "-i", str(wav), "-map", "0:v:0", "-map", "1:a:0", "-vf", vf,
           "-c:v", "libx264", "-preset", "slow", "-crf", "14" if not a.draft else "20", "-profile:v", "high",
           "-x264-params", "aq-mode=3:aq-strength=0.85",
           "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
           "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-movflags", "+faststart", "-shortest", str(out)]
    subprocess.run(cmd, check=True)
    print(f"video: {out} ({out.stat().st_size / 1e6:.1f} MB) in {time.time() - t0:.0f}s total", flush=True)
    if a.clean:
        for p in fdir.glob("f*.png"):
            p.unlink()


if __name__ == "__main__":
    main()
