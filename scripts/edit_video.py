#!/usr/bin/env python3
"""Edit a raw screen recording of scripts/demo.sh into a post-ready 1080p video.

- Puts the Ghostty window on a dark canvas, with rounded corners masked so no desktop shows through.
- Detects when tfsee's graph appears and eases the camera in on it, so it reads on a phone.
- Adds a small Ghostty badge (icon pulled from the installed app at runtime, not stored in the repo).
- Ends on a short title card.

Usage: python scripts/edit_video.py raw.mov out.mp4 [--icon /path/to/icon.png]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1920, 1080, 30
PANEL = (13, 17, 23)  # tfsee's graph background (#0d1117)
CANVAS_TOP, CANVAS_BOTTOM = (16, 20, 28), (6, 7, 10)
ZOOM_SECONDS, HOLD_AFTER_GRAPH, CARD_SECONDS, FADE = 0.8, 11.0, 2.6, 0.45


def font(size: int, mono: bool = False):
    paths = ["/System/Library/Fonts/SFNSMono.ttf"] if mono else ["/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc"]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def probe(path: Path) -> tuple[int, int]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height", "-of", "json", str(path)], capture_output=True, text=True, check=True)
    s = json.loads(out.stdout)["streams"][0]
    return s["width"], s["height"]


def frames(path: Path, size: tuple[int, int]):
    proc = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-i", str(path), "-vf", f"fps={FPS}", "-f", "rawvideo",
                             "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    n = size[0] * size[1] * 3
    while True:
        raw = proc.stdout.read(n)
        if len(raw) < n:
            break
        yield Image.frombytes("RGB", size, raw)
    proc.wait()


def panel_box(img: Image.Image):
    """Bounding box of tfsee's graph panel (its #0d1117 background) in the lower part of the window."""
    small = img.resize((img.width // 4, img.height // 4))
    diff = ImageChops.difference(small, Image.new("RGB", small.size, PANEL)).convert("L")
    mask = diff.point(lambda v: 255 if v < 7 else 0)
    w, h = mask.size
    count = lambda region: mask.crop(region).histogram()[255]  # noqa: E731  (pixels matching the panel)
    rows = [y for y in range(h // 3, h) if count((0, y, w, y + 1)) > w * 0.5]
    if len(rows) < h * 0.1:
        return None
    cols = [x for x in range(w) if count((x, rows[0], x + 1, rows[-1])) > (rows[-1] - rows[0]) * 0.5]
    return (cols[0] * 4, rows[0] * 4, (cols[-1] + 1) * 4, (rows[-1] + 1) * 4) if cols else None


def ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def lerp(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("raw", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--icon", type=Path, help="Ghostty icon PNG (extract with sips from Ghostty.app)")
    args = ap.parse_args()

    size = probe(args.raw)
    src = list(frames(args.raw, size))

    # When does the graph appear, and where is it?
    t_graph = next((i for i, f in enumerate(src) if i % 3 == 0 and panel_box(f)), None)
    if t_graph is None:
        raise SystemExit("couldn't find tfsee's graph in the recording")
    box = panel_box(src[min(len(src) - 1, t_graph + FPS * 2)])
    pad_x, pad_y = 2, 2  # crop to the graph panel itself; any looser shows clipped terminal text around it
    zoom_src = (box[0] - pad_x, box[1] - pad_y, box[2] + pad_x, box[3] + pad_y)
    end = min(len(src), t_graph + int(HOLD_AFTER_GRAPH * FPS))

    # Canvas: subtle vertical gradient.
    canvas = Image.new("RGB", (W, H))
    cd = ImageDraw.Draw(canvas)
    for y in range(H):
        cd.line((0, y, W, y), fill=tuple(round(c) for c in lerp(CANVAS_TOP, CANVAS_BOTTOM, y / H)))

    full_src = (0, 0, size[0], size[1])
    fit_h = 940
    fit_w = fit_h * size[0] / size[1]
    full_dst = ((W - fit_w) / 2, (H - fit_h) / 2 - 10, (W + fit_w) / 2, (H + fit_h) / 2 - 10)
    zw = 1800
    zh = zw * (zoom_src[3] - zoom_src[1]) / (zoom_src[2] - zoom_src[0])
    zoom_dst = ((W - zw) / 2, (H - zh) / 2 - 20, (W + zw) / 2, (H + zh) / 2 - 20)

    # Badge: ghost + label, bottom right.
    badge = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(badge)
    label, sub = "Ghostty 1.4", "Kitty graphics"
    lf, sf = font(26), font(18)
    tx = W - 48 - max(lf.getlength(label), sf.getlength(sub))
    if args.icon and args.icon.exists():
        icon = Image.open(args.icon).convert("RGBA").resize((58, 58), Image.LANCZOS)
        badge.alpha_composite(icon, (int(tx - 70), H - 92))
    bd.text((tx, H - 92), label, font=lf, fill=(230, 237, 243, 255))
    bd.text((tx, H - 60), sub, font=sf, fill=(139, 148, 158, 255))

    def window_mask(w: int, h: int, radius: int):
        m = Image.new("L", (w, h), 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
        return m

    def compose(frame: Image.Image, k: float) -> Image.Image:
        s = lerp(full_src, zoom_src, k)
        d = lerp(full_dst, zoom_dst, k)
        view = frame.crop(tuple(round(v) for v in s)).resize((round(d[2] - d[0]), round(d[3] - d[1])), Image.LANCZOS)
        out = canvas.copy()
        shadow = Image.new("L", (W, H), 0)
        ImageDraw.Draw(shadow).rounded_rectangle((d[0], d[1] + 16, d[2], d[3] + 16), radius=24, fill=150)
        out.paste((0, 0, 0), (0, 0), shadow.filter(ImageFilter.GaussianBlur(28)))
        out.paste(view, (round(d[0]), round(d[1])), window_mask(view.width, view.height, round(22 * (1 - k) + 14 * k)))
        out = out.convert("RGBA")
        out.alpha_composite(badge)
        return out.convert("RGB")

    # End card.
    card = canvas.copy().convert("RGBA")
    cdraw = ImageDraw.Draw(card)
    if args.icon and args.icon.exists():
        big = Image.open(args.icon).convert("RGBA").resize((150, 150), Image.LANCZOS)
        card.alpha_composite(big, ((W - 150) // 2, 270))
    for text, f, color, y in (("tfsee", font(96, mono=True), (230, 237, 243), 450),
                              ("terraform plan, as a graph in your terminal", font(40), (201, 209, 217), 580),
                              ("built on Ghostty 1.4's Kitty graphics · open source", font(28), (139, 148, 158), 645)):
        cdraw.text(((W - f.getlength(text)) / 2, y), text, font=f, fill=color)
    card = card.convert("RGB")

    enc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "17",
                            "-preset", "slow", "-movflags", "+faststart", str(args.out)], stdin=subprocess.PIPE)
    last = None
    for i in range(end):
        k = ease((i - t_graph) / (ZOOM_SECONDS * FPS)) if i >= t_graph else 0.0
        last = compose(src[i], k)
        enc.stdin.write(last.tobytes())
    for j in range(int(CARD_SECONDS * FPS)):
        a = ease(j / (FADE * FPS))
        enc.stdin.write(Image.blend(last, card, a).tobytes())
    enc.stdin.close()
    enc.wait()
    print(f"graph appears at {t_graph / FPS:.1f}s · wrote {args.out} ({(end + CARD_SECONDS * FPS) / FPS:.1f}s)")


if __name__ == "__main__":
    main()
