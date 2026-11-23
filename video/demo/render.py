"""Turn a recorded timeline (lib.py) into a finished mp4: smooth zoom/pan, speed-ups, captions, title cards.

  .venv/bin/python video/demo/render.py <workdir> <clip> <out.mp4> --kicker "01 / ASK" --title "..." --sub "..."
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OW, OH, FPS = 1920, 1080, 30
BG = (9, 11, 14)
ACCENT = (255, 211, 61)
FADE = 0.35


# ---------------------------------------------------------------------------- fonts
def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    try:
        f = ImageFont.truetype("/System/Library/Fonts/SFNS.ttf", size)
        try:
            f.set_variation_by_name("Bold" if bold else "Regular")
        except Exception:
            pass
        return f
    except Exception:
        return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)


# ---------------------------------------------------------------------------- encoder
class Encoder:
    def __init__(self, out: Path):
        out.parent.mkdir(parents=True, exist_ok=True)
        self.p = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{OW}x{OH}",
             "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)
        self.n = 0

    def write(self, im: Image.Image):
        self.p.stdin.write(im.convert("RGB").tobytes())
        self.n += 1

    def close(self):
        self.p.stdin.close()
        self.p.wait()


def fade(im: Image.Image, a: float) -> Image.Image:
    return im if a >= 0.999 else Image.blend(Image.new("RGB", im.size, (0, 0, 0)), im, max(0.0, a))


# ---------------------------------------------------------------------------- title card
def card_frames(enc: Encoder, kicker: str, title: str, sub: str, seconds: float = 2.4):
    n = int(seconds * FPS)
    for i in range(n):
        t = i / FPS
        im = Image.new("RGB", (OW, OH), BG)
        d = ImageDraw.Draw(im)
        for x in range(0, OW, 96):                       # faint tactical grid
            d.line([(x, 0), (x, OH)], fill=(16, 19, 24), width=1)
        for y in range(0, OH, 96):
            d.line([(0, y), (OW, y)], fill=(16, 19, 24), width=1)
        slide = int(24 * (1 - min(1, t / 0.7)) ** 3)      # text eases in from the right
        d.rectangle([160, 400, 168, 590], fill=ACCENT)
        d.text((200 + slide, 392), kicker.upper(), font=font(30, True), fill=ACCENT)
        d.text((200 + slide, 440), title, font=font(86, True), fill=(244, 246, 248))
        d.text((200 + slide, 552), sub, font=font(36), fill=(150, 158, 168))
        d.text((OW - 330, OH - 90), "PARSE · Kosovo OSINT", font=font(26, True), fill=(90, 98, 108))
        a = min(1.0, t / FADE, (seconds - t) / FADE)
        enc.write(fade(im, a))


# ---------------------------------------------------------------------------- caption overlay
def draw_caption(im: Image.Image, text: str, sub: str, alpha: float) -> Image.Image:
    f1, f2 = font(40, True), font(27)
    d0 = ImageDraw.Draw(im)
    w1 = d0.textlength(text, font=f1)
    w2 = d0.textlength(sub, font=f2) if sub else 0
    bw = int(max(w1, w2)) + 96
    bh = 112 if sub else 88
    x0, y0 = 64, OH - 64 - bh
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=14, fill=(8, 10, 13, int(215 * alpha)))
    d.rectangle([x0, y0 + 14, x0 + 6, y0 + bh - 14], fill=ACCENT + (int(255 * alpha),))
    d.text((x0 + 36, y0 + (14 if sub else 20)), text, font=f1, fill=(255, 255, 255, int(255 * alpha)))
    if sub:
        d.text((x0 + 36, y0 + 64), sub, font=f2, fill=(176, 184, 194, int(255 * alpha)))
    return Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB")


# ---------------------------------------------------------------------------- camera
def lerp(a, b, u):
    return a + (b - a) * u


def cam_at(cams: list[dict], s: float) -> tuple[float, float, float]:
    state = (1.0, 0.5, 0.5)
    for k in cams:
        if k["t"] > s:
            break
        tgt = (k["z"], k["cx"], k["cy"])
        u = (s - k["t"]) / max(k["dur"], 1e-3)
        if u >= 1:
            state = tgt
            continue
        e = u * u * (3 - 2 * u)
        z = math.exp(lerp(math.log(state[0]), math.log(tgt[0]), e))
        return z, lerp(state[1], tgt[1], e), lerp(state[2], tgt[2], e)
    return state


# ---------------------------------------------------------------------------- one clip
def render_clip(workdir: Path, name: str, out: Path, kicker="", title="", sub="", card_s=2.4,
                trim_start=0.0, trim_end=0.0):
    tl = json.loads((workdir / name / "timeline.json").read_text())
    fdir = workdir / name / "f"
    ts = [t for t, _ in tl["frames"]]
    files = [f for _, f in tl["frames"]]
    cams = sorted(tl["cams"], key=lambda k: k["t"])
    caps = sorted(tl["caps"], key=lambda k: k["t"])
    speeds = tl["speeds"]
    s = tl["marks"]["start"] + trim_start
    s_end = tl["marks"]["end"] - trim_end
    SW, SH = tl["w"], tl["h"]

    enc = Encoder(out)
    if title:
        card_frames(enc, kicker, title, sub, card_s)
    n_card = enc.n

    idx, cur_img = -1, None
    shown: list[dict] = []
    ci = 0
    while ci < len(caps) and caps[ci]["t"] < s - 1.5:   # captions from well before the trim point are dropped
        ci += 1
    while s < s_end:
        f = 1.0
        for sp in speeds:
            if sp["t0"] <= s < sp["t1"]:
                f = sp["f"]
                break
        out_t = (enc.n - n_card) / FPS
        while ci < len(caps) and caps[ci]["t"] <= s:
            shown.append({**caps[ci], "o0": out_t})
            ci += 1
        j = max(0, bisect.bisect_right(ts, s) - 1)
        if j != idx:
            idx = j
            cur_img = Image.open(fdir / files[j]).convert("RGB")
        z, cx, cy = cam_at(cams, s)
        bw, bh = SW / z, SH / z
        l = min(max(cx * SW - bw / 2, 0), SW - bw)
        t_ = min(max(cy * SH - bh / 2, 0), SH - bh)
        if z == 1.0 and (SW, SH) == (OW, OH):
            im = cur_img
        else:
            im = cur_img.resize((OW, OH), Image.LANCZOS, box=(l, t_, l + bw, t_ + bh))
        for c in shown:
            age = out_t - c["o0"]
            if 0 <= age < c["dur"]:
                a = min(1.0, age / 0.3, (c["dur"] - age) / 0.3)
                im = draw_caption(im, c["text"], c["sub"], max(0.0, a))
        lead = (enc.n - n_card) / FPS
        tail = (s_end - s) / max(f, 1e-6)
        im = fade(im, min(1.0, lead / FADE if not title else 1.0, tail / FADE))
        enc.write(im)
        s += f / FPS
    enc.close()
    dur = enc.n / FPS
    print(f"[{name}] -> {out} ({dur:.1f}s)")
    return dur


def concat(parts: list[Path], out: Path):
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                    "-movflags", "+faststart", str(out)], check=True)
    lst.unlink()
    print("concat ->", out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("clip")
    ap.add_argument("out")
    ap.add_argument("--kicker", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--sub", default="")
    ap.add_argument("--trim-start", type=float, default=0.0)
    ap.add_argument("--trim-end", type=float, default=0.0)
    a = ap.parse_args()
    render_clip(Path(a.workdir), a.clip, Path(a.out), a.kicker, a.title, a.sub,
                trim_start=a.trim_start, trim_end=a.trim_end)
