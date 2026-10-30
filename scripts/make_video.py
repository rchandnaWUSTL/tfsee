#!/usr/bin/env python3
"""Render the demo video from a real run, without screen recording.

Runs the real `terraform plan` on examples/demo, captures Terraform's actual output and the real
tfsee graph frames, then draws them as a terminal session (typing, scrolling output, the graph
playing the apply order) and encodes an MP4 with ffmpeg.

Terminal recorders like asciinema can't capture the graph: it's drawn with the Kitty graphics
protocol, which their players don't render. This draws exactly what Ghostty shows instead.

Usage: python scripts/make_video.py [out.mp4]
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tfsee.plan import build  # noqa: E402
from tfsee.render import BG, _font, draw  # noqa: E402

DEMO = ROOT / "examples" / "demo"
W, H, FPS = 1920, 1080, 30
CMD = "terraform plan -var stage=v2"
PROMPT = [("tfsee/examples/demo", "#8b949e", False), (" $ ", "#3fbfa8", True)]
ANSI = {30: "#484f58", 31: "#ff6f61", 32: "#3fbfa8", 33: "#e8b13a", 34: "#58a6ff", 35: "#a98bff",
        36: "#39c5cf", 37: "#e6edf3", 90: "#6e7681", 91: "#ff6f61", 92: "#56d4bc", 93: "#f2c75c",
        94: "#79c0ff", 95: "#bc8cff", 96: "#56d4dd", 97: "#ffffff"}
INK, CHROME = "#e6edf3", "#161b22"


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, cwd=DEMO, check=True, capture_output=True, text=True).stdout


def parse_ansi(text: str) -> list[list[tuple[str, str, bool]]]:
    """Terraform's colored output -> lines of (text, color, bold) segments."""
    lines, color, bold = [], INK, False
    for raw in text.splitlines():
        segs, pos = [], 0
        for m in re.finditer(r"\x1b\[([0-9;]*)m", raw):
            if m.start() > pos:
                segs.append((raw[pos:m.start()], color, bold))
            for code in [int(c) for c in m.group(1).split(";") if c] or [0]:
                if code == 0:
                    color, bold = INK, False
                elif code == 1:
                    bold = True
                elif code == 22:
                    bold = False
                elif code == 39:
                    color = INK
                elif code in ANSI:
                    color = ANSI[code]
            pos = m.end()
        segs.append((raw[pos:], color, bold))
        lines.append([s for s in segs if s[0]])
    return lines


def main(out: Path) -> None:
    run(["terraform", "init", "-input=false"])
    run(["terraform", "apply", "-auto-approve", "-input=false"])  # start from the v1 infra
    (DEMO / ".terraform").mkdir(exist_ok=True)  # configs without providers never create it
    plan_text = run(["terraform", "plan", "-input=false", "-compact-warnings", "-var", "stage=v2",
                     "-out=.terraform/tfsee.tfplan"])
    nodes = build(json.loads(run(["terraform", "show", "-json", ".terraform/tfsee.tfplan"])))
    output = parse_ansi(plan_text)

    font = _font(22)
    bold = _font(22)
    cell_w, line_h = font.getlength("M"), 30
    margin, bar_h, pad = 40, 44, 26
    term = (margin + pad, margin + bar_h + pad, W - margin - pad, H - margin - pad)
    rows = int((term[3] - term[1]) // line_h)
    cols = int((term[2] - term[0]) // cell_w)

    # The real graph frames, scaled to the terminal width the way Ghostty scales them.
    steps = max(n.wave for n in nodes.values())
    graph_frames = [draw(nodes, applied_through=w, text_scale=1.4) for w in range(steps + 1)] + [draw(nodes, text_scale=1.4)]
    gw = term[2] - term[0]
    gh = round(graph_frames[0].height * gw / graph_frames[0].width)
    graph_frames = [g.resize((gw, gh), Image.LANCZOS) for g in graph_frames]
    graph_rows = -(-gh // line_h)

    def wrap(line):
        """Split a segment line at the terminal width."""
        out_lines, cur, n = [], [], 0
        for text, color, b in line:
            while text:
                take = text[:cols - n]
                cur.append((take, color, b))
                n += len(take)
                text = text[len(take):]
                if n >= cols:
                    out_lines.append(cur)
                    cur, n = [], 0
        out_lines.append(cur)
        return out_lines

    def frame(buffer, cursor=False, graph=None):
        img = Image.new("RGB", (W, H), "#05070a")
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((margin, margin, W - margin, H - margin), radius=14, fill=BG, outline="#30363d", width=2)
        d.rounded_rectangle((margin, margin, W - margin, margin + bar_h), radius=14, fill=CHROME)
        d.rectangle((margin, margin + bar_h - 14, W - margin, margin + bar_h), fill=CHROME)
        for i, c in enumerate(("#ff5f57", "#febc2e", "#28c840")):
            cx = margin + 26 + i * 22
            d.ellipse((cx - 7, margin + bar_h / 2 - 7, cx + 7, margin + bar_h / 2 + 7), fill=c)
        title = "tfsee — examples/demo"
        d.text(((W - font.getlength(title) * 0.7) / 2, margin + 12), title, font=_font(16), fill="#8b949e")
        text_rows = rows - (graph_rows + 1 if graph else 0)
        visible = [w for line in buffer for w in wrap(line)][-text_rows:] if text_rows > 0 else []
        for r, segs in enumerate(visible):
            x, y = term[0], term[1] + r * line_h
            for text, color, b in segs:
                d.text((x, y), text, font=bold if b else font, fill=color)
                x += cell_w * len(text)
            if cursor and r == len(visible) - 1:
                d.rectangle((x + 2, y + 3, x + cell_w, y + line_h - 4), fill="#c9d1d9")
        if graph:
            img.paste(graph, (term[0], int(term[1] + len(visible) * line_h + line_h * 0.5)))
        return img

    frames: list[tuple[Image.Image, int]] = []  # (image, how many video frames to hold it)
    prompt = list(PROMPT)
    for i in range(int(0.9 * FPS / 8)):  # blinking cursor at the prompt
        frames.append((frame([prompt], cursor=i % 2 == 0), 8))
    for i in range(1, len(CMD) + 1):  # typing
        frames.append((frame([prompt + [(CMD[:i], INK, False)]], cursor=True), 2))
    frames.append((frame([prompt + [(CMD, INK, False)]], cursor=True), int(0.5 * FPS)))
    typed = prompt + [(CMD, INK, False)]
    for n in range(0, len(output) + 1, 3):  # Terraform's output scrolling in
        frames.append((frame([typed] + output[:n]), 1))
    buffer = [typed] + output
    for _ in range(2):  # the graph plays the apply order, then holds; twice
        for g in graph_frames[:-1]:
            frames.append((frame(buffer, graph=g), int(0.9 * FPS)))
        frames.append((frame(buffer, graph=graph_frames[-1]), int(3.0 * FPS)))

    ffmpeg = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                               "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt",
                               "yuv420p", "-crf", "16", "-preset", "slow", "-movflags", "+faststart", str(out)],
                              stdin=subprocess.PIPE)
    for img, hold in frames:
        raw = img.tobytes()
        for _ in range(hold):
            ffmpeg.stdin.write(raw)
    ffmpeg.stdin.close()
    ffmpeg.wait()
    seconds = sum(h for _, h in frames) / FPS
    print(f"wrote {out} ({seconds:.1f}s, {W}x{H})")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "media" / "tfsee-demo.mp4").resolve())
