"""Draw the plan graph with Pillow: one column per apply wave, colored by action."""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

from .plan import Node, summary

COLORS = {"create": "#3fb950", "update": "#d29922", "delete": "#f85149", "replace": "#bc8cff",
          "read": "#58a6ff", "no-op": "#6e7681"}
SYMBOLS = {"create": "+", "update": "~", "delete": "-", "replace": "±", "read": "<=", "no-op": " "}
BG, INK, MUTED, EDGE = "#0d1117", "#e6edf3", "#7d8590", "#30363d"
FONTS = ["/System/Library/Fonts/SFNSMono.ttf", "/System/Library/Fonts/Menlo.ttc",
         "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "DejaVuSansMono.ttf"]


def _font(size: int):
    for path in FONTS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _mix(hex_color: str, amount: float) -> tuple[int, int, int]:
    """Blend a color toward the background; amount=1 is the full color."""
    c = tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(BG[i:i + 2], 16) for i in (1, 3, 5))
    return tuple(round(b[i] + (c[i] - b[i]) * amount) for i in range(3))


def layout(nodes: dict[str, Node], font, pad_x: int, box_h: int, gap_x: int, gap_y: int):
    """Columns by apply wave; within a column, order by the average row of a node's dependencies."""
    waves = max((n.wave for n in nodes.values()), default=0)
    columns = [sorted(a for a, n in nodes.items() if n.wave == w) for w in range(waves + 1)]
    row = {}
    for w, col in enumerate(columns):
        if w:
            col.sort(key=lambda a: (sum(row[d] for d in nodes[a].deps) / len(nodes[a].deps)) if nodes[a].deps else 0)
        for i, addr in enumerate(col):
            row[addr] = i
    widths = {a: font.getbbox(f"{SYMBOLS[n.action]} {a}")[2] + 2 * pad_x for a, n in nodes.items()}
    tallest = max(len(c) for c in columns)
    boxes, x = {}, 0
    for col in columns:
        col_w = max(widths[a] for a in col)
        offset = (tallest - len(col)) * (box_h + gap_y) / 2
        for i, addr in enumerate(col):
            y = offset + i * (box_h + gap_y)
            boxes[addr] = (x, y, x + widths[addr], y + box_h)
        x += col_w + gap_x
    return boxes, x - gap_x, tallest * (box_h + gap_y) - gap_y


def draw(nodes: dict[str, Node], applied_through: int | None = None, scale: int = 2) -> Image.Image:
    """applied_through=None draws the finished plan; an int draws an apply-order animation frame
    where waves after it are still pending (dimmed) and that wave is the one applying now (glowing)."""
    s = scale
    font, small, title_font = _font(15 * s), _font(12 * s), _font(17 * s)
    boxes, graph_w, graph_h = layout(nodes, font, pad_x=14 * s, box_h=34 * s, gap_x=56 * s, gap_y=14 * s)
    margin, head, foot = 28 * s, 54 * s, 46 * s
    width = max(graph_w + 2 * margin, 560 * s)
    img = Image.new("RGB", (int(width), int(graph_h + head + foot + 2 * margin)), BG)
    d = ImageDraw.Draw(img)
    ox, oy = margin + (width - 2 * margin - graph_w) / 2, margin + head

    add, change, destroy = summary(nodes)
    d.text((margin, margin), "tfsee", font=title_font, fill=INK)
    d.text((margin + 70 * s, margin + 2 * s), f"Plan: {add} to add, {change} to change, {destroy} to destroy",
           font=font, fill=MUTED)

    def state(n: Node) -> str:
        if applied_through is None or n.action == "no-op":
            return "done"
        return "done" if n.wave < applied_through else "now" if n.wave == applied_through else "pending"

    for addr, n in nodes.items():  # edges first, under the boxes
        for dep in n.deps:
            x0, y0 = ox + boxes[dep][2], oy + (boxes[dep][1] + boxes[dep][3]) / 2
            x1, y1 = ox + boxes[addr][0], oy + (boxes[addr][1] + boxes[addr][3]) / 2
            pts = []
            for i in range(25):
                t = i / 24
                bx = (1 - t) ** 3 * x0 + 3 * (1 - t) ** 2 * t * (x0 + 28 * s) + 3 * (1 - t) * t ** 2 * (x1 - 28 * s) + t ** 3 * x1
                by = (1 - t) ** 3 * y0 + 3 * (1 - t) ** 2 * t * y0 + 3 * (1 - t) * t ** 2 * y1 + t ** 3 * y1
                pts.append((bx, by))
            lit = state(n) != "pending"
            d.line(pts, fill=_mix(COLORS[n.action], 0.55) if lit and n.action != "no-op" else EDGE, width=2 * s)

    for addr, n in nodes.items():
        x0, y0, x1, y1 = boxes[addr]
        box = (ox + x0, oy + y0, ox + x1, oy + y1)
        color, st = COLORS[n.action], state(n)
        if st == "now":  # glow ring on the wave being applied
            d.rounded_rectangle((box[0] - 5 * s, box[1] - 5 * s, box[2] + 5 * s, box[3] + 5 * s),
                                radius=12 * s, outline=_mix(color, 0.5), width=3 * s)
        fill = _mix(color, 0.22 if st != "pending" else 0.06)
        outline = _mix(color, 1.0 if st != "pending" else 0.35)
        d.rounded_rectangle(box, radius=8 * s, fill=fill, outline=outline, width=2 * s)
        label = f"{SYMBOLS[n.action]} {addr}"
        text_color = INK if st != "pending" and n.action != "no-op" else MUTED
        ty = box[1] + (box[3] - box[1] - font.getbbox(label)[3]) / 2
        d.text((box[0] + 14 * s, ty), label, font=font, fill=text_color)
        if n.action == "delete" and st == "done":
            mid = (box[1] + box[3]) / 2
            d.line((box[0] + 30 * s, mid + 2 * s, box[0] + 14 * s + font.getbbox(label)[2], mid + 2 * s),
                   fill=_mix(color, 0.9), width=2 * s)

    x, y = margin, img.height - margin - 16 * s  # legend
    for action in ("create", "update", "replace", "delete", "no-op"):
        d.rounded_rectangle((x, y, x + 14 * s, y + 14 * s), radius=3 * s, fill=_mix(COLORS[action], 0.6))
        name = {"no-op": "unchanged", "delete": "destroy"}.get(action, action)
        d.text((x + 20 * s, y - 1 * s), name, font=small, fill=MUTED)
        x += 20 * s + small.getbbox(name)[2] + 22 * s
    return img


def png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
