#!/usr/bin/env python3
"""Edit a raw screen recording of scripts/demo.sh into a post-ready 1080p video.

- Puts the Ghostty window on a dark canvas, with rounded corners masked so no desktop shows through.
- Pushes in on the prompt while `terraform plan` is typed, then pulls back over about a second as
  the output scrolls, landing on the whole terminal right as tfsee's graph appears.
- Plays the graph's apply steps inside the terminal and ends on the finished graph.
- Adds a small Ghostty badge (icon pulled from the installed app at runtime, not stored in the repo).
- Optionally ends on a short title card (--card).
Timing (typing, output, graph) is detected from the recording, not hard-coded.

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
CARD_SECONDS, FADE = 2.6, 0.45
STEP_SECONDS = 0.9  # tfsee's default --speed; the graph shows step 1 the moment it appears
FREEZE = 1.2  # hold on the finished graph at the end
FOCUS_ZOOM, FOCUS_IN, PULL_BACK = 1.5, 0.9, 1.4  # push-in on the command; seconds to ease in / pull back


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
    ap.add_argument("--card", action="store_true", help="end on a title card")
    args = ap.parse_args()

    size = probe(args.raw)
    src = list(frames(args.raw, size))

    # Timing, from the pixels: when the graph appears, when typing starts, when the output lands.
    t_graph = next((i for i, f in enumerate(src) if i % 3 == 0 and panel_box(f)), None)
    if t_graph is None:
        raise SystemExit("couldn't find tfsee's graph in the recording")
    prompt_band = (0, int(size[1] * 0.12))

    def bright(f, box):
        return f.crop(box).convert("L").point(lambda v: 255 if v > 150 else 0)

    def right_edge(f):  # rightmost bright pixel on the prompt line; the cursor never moves it right
        b = bright(f, (0, prompt_band[0], size[0], prompt_band[1])).getbbox()
        return b[2] if b else 0

    def rows_below(f):  # 8px stripes with text under the prompt line (Terraform's output)
        g = bright(f, (0, prompt_band[1], size[0], size[1]))
        return sum(1 for y in range(0, g.height, 8) if g.crop((0, y, g.width, y + 8)).getbbox())

    char_w = size[0] / 118  # demo window is 118 columns wide
    prompt_edge = max(right_edge(f) for f in src[:FPS // 2])  # prompt plus the blinking cursor
    t_type = next(i for i in range(t_graph) if right_edge(src[i]) > prompt_edge + 1.5 * char_w)
    t_output = next(i for i in range(t_type, t_graph) if rows_below(src[i]) > 10)
    steps = 6  # the demo plan's apply steps (examples/demo)
    # tfsee holds the finished graph for 3 steps' worth, then loops; end just before it restarts.
    end = min(len(src), t_graph + int((steps + 3) * STEP_SECONDS * FPS) - 2)

    # Canvas: subtle vertical gradient.
    canvas = Image.new("RGB", (W, H))
    cd = ImageDraw.Draw(canvas)
    for y in range(H):
        cd.line((0, y, W, y), fill=tuple(round(c) for c in lerp(CANVAS_TOP, CANVAS_BOTTOM, y / H)))

    fit_h = 960
    fit_w = round(fit_h * size[0] / size[1])
    win = ((W - fit_w) // 2, (H - fit_h) // 2)
    mask = Image.new("L", (fit_w, fit_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, fit_w - 1, fit_h - 1), radius=20, fill=255)
    shadow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(shadow).rounded_rectangle((win[0], win[1] + 16, win[0] + fit_w, win[1] + fit_h + 16), radius=24, fill=150)
    shadow = shadow.filter(ImageFilter.GaussianBlur(28))
    base = canvas.copy()
    base.paste((0, 0, 0), (0, 0), shadow)

    # Where the typed command sits on the canvas: the push-in centers on it (kept inside the canvas).
    typed = bright(src[t_output - 1], (0, prompt_band[0], size[0], prompt_band[1])).getbbox() or (0, 0, size[0] // 3, prompt_band[1])
    scale = fit_w / size[0]
    cx = win[0] + (typed[0] + typed[2]) / 2 * scale
    cy = win[1] + (prompt_band[0] + (typed[1] + typed[3]) / 2) * scale
    vw, vh = W / FOCUS_ZOOM, H / FOCUS_ZOOM
    vx = min(max(cx - vw / 2, 0), W - vw)
    vy = min(max(cy - vh / 2, 0), H - vh)
    focus_view, full_view = (vx, vy, vx + vw, vy + vh), (0, 0, W, H)

    # Badge: ghost + name, bottom right; it stays put while the camera moves.
    badge = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(badge)
    label = "Ghostty 1.4"
    lf = font(24)
    tx = W - 40 - lf.getlength(label)  # sits right of the window, never on top of it
    if args.icon and args.icon.exists():
        icon = Image.open(args.icon).convert("RGBA").resize((48, 48), Image.LANCZOS)
        badge.alpha_composite(icon, (int(tx - 58), H - 80))
    bd.text((tx, H - 80 + (48 - 24) / 2 - 3), label, font=lf, fill=(230, 237, 243, 255))

    def compose(frame: Image.Image, k: float) -> Image.Image:
        out = base.copy()
        out.paste(frame.resize((fit_w, fit_h), Image.LANCZOS), win, mask)
        if k > 0:
            v = lerp(full_view, focus_view, k)
            out = out.crop(tuple(round(x) for x in v)).resize((W, H), Image.LANCZOS)
        out = out.convert("RGBA")
        out.alpha_composite(badge)
        return out.convert("RGB")

    # End card (optional).
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
    start_in = max(0, t_type - int(0.35 * FPS))
    last = None
    for i in range(end):
        if i < t_output:
            k = ease((i - start_in) / (FOCUS_IN * FPS))  # push in while the command is typed
        else:
            k = 1 - ease((i - t_output) / (PULL_BACK * FPS))  # pull back as the output scrolls
        last = compose(src[i], k)
        enc.stdin.write(last.tobytes())
    for _ in range(int(FREEZE * FPS)):
        enc.stdin.write(last.tobytes())
    for j in range(int(CARD_SECONDS * FPS) if args.card else 0):
        enc.stdin.write(Image.blend(last, card, ease(j / (FADE * FPS))).tobytes())
    enc.stdin.close()
    enc.wait()
    total = end + FREEZE * FPS + (CARD_SECONDS * FPS if args.card else 0)
    print(f"typing {t_type / FPS:.1f}s · output {t_output / FPS:.1f}s · graph {t_graph / FPS:.1f}s · "
          f"wrote {args.out} ({total / FPS:.1f}s)")


if __name__ == "__main__":
    main()
