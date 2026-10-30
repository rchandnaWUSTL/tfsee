"""Draw the plan graph with Pillow: one column per apply step, colored by action.

Design choices, each for a reason:
- Colors pass a colorblind check (deuteranopia, protanopia, tritanopia) against the dark background,
  and every node also carries Terraform's symbol (+ ~ ± -), so color is never the only cue.
- Fewer edge crossings: node order within a column is refined with up-and-down barycenter sweeps.
  Crossings are the biggest drag on reading a node-link diagram (Purchase's studies).
- Hierarchy: the resource name is the big text; its type sits small above it. Unchanged resources
  are drawn quietly so the changes stand out. Totals sit at the top as colored chips.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

from .plan import Node, resource_of, summary

# Validated (dataviz validate_palette.js, dark mode, all pairs): colorblind ΔE ≥ 8.7, normal ΔE ≥ 16.9,
# contrast ≥ 3:1 on BG. Slightly lighter than the dark-mode band on purpose: amber darkened into the
# band becomes indistinguishable from red, and these colors only draw outlines, edges and swatches.
COLORS = {"create": "#3fbfa8", "update": "#e8b13a", "replace": "#a98bff", "delete": "#ff6f61",
          "read": "#58a6ff", "no-op": "#6e7681"}
SYMBOLS = {"create": "+", "update": "~", "delete": "-", "replace": "±", "read": "<=", "no-op": "·"}
BG, INK, MUTED, FAINT, EDGE = "#0d1117", "#e6edf3", "#8b949e", "#484f58", "#262c34"
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


def _split(address: str) -> tuple[str, str]:
    """'module.net.aws_subnet.private[0]' -> ('module.net.aws_subnet', 'private[0]')."""
    resource = resource_of(address)
    prefix, _, name = resource.rpartition(".")
    return prefix, name + address[len(resource):]


def _order(nodes: dict[str, Node]) -> list[list[str]]:
    """Columns by apply step; order within columns by barycenter sweeps to cut edge crossings."""
    steps = max((n.wave for n in nodes.values()), default=0)
    columns = [sorted(a for a, n in nodes.items() if n.wave == w) for w in range(steps + 1)]
    dependents = {a: [b for b, n in nodes.items() if a in n.deps] for a in nodes}
    pos = {a: i for col in columns for i, a in enumerate(col)}

    def sweep(col: list[str], neighbors) -> None:
        def key(a):
            near = [pos[x] for x in neighbors(a) if x in pos]
            return (sum(near) / len(near)) if near else pos[a]
        col.sort(key=key)
        for i, a in enumerate(col):
            pos[a] = i

    for _ in range(4):
        for col in columns[1:]:
            sweep(col, lambda a: nodes[a].deps)
        for col in reversed(columns[:-1]):
            sweep(col, lambda a: dependents[a])
    return columns


def draw(nodes: dict[str, Node], applied_through: int | None = None, scale: int = 2) -> Image.Image:
    """applied_through=None draws the finished plan; an int draws an apply-order animation frame
    where later steps are still pending (dimmed) and that step is the one applying now (glowing)."""
    s = scale
    name_font, type_font, small, title = _font(15 * s), _font(11 * s), _font(12 * s), _font(18 * s)
    pad_x, box_h, gap_x, gap_y = 14 * s, 46 * s, 64 * s, 16 * s

    columns = _order(nodes)
    width_of = {}
    for a, n in nodes.items():
        prefix, name = _split(a)
        width_of[a] = max(name_font.getbbox(f"{SYMBOLS[n.action]} {name}")[2], type_font.getbbox(prefix)[2]) + 2 * pad_x
    col_w = [max(width_of[a] for a in col) for col in columns]
    tallest = max(len(c) for c in columns)
    graph_w = sum(col_w) + gap_x * (len(columns) - 1)
    graph_h = tallest * (box_h + gap_y) - gap_y

    margin, head, step_row, foot = 32 * s, 58 * s, 26 * s, 44 * s
    width = int(max(graph_w + 2 * margin, 640 * s))
    img = Image.new("RGB", (width, int(graph_h + head + step_row + foot + 2 * margin)), BG)
    d = ImageDraw.Draw(img)
    ox = margin + (width - 2 * margin - graph_w) / 2
    oy = margin + head + step_row

    # Header: title, then the totals as chips (bottom line first).
    d.text((margin, margin), "terraform plan", font=title, fill=INK)
    add, change, destroy = summary(nodes)
    x = margin + title.getbbox("terraform plan")[2] + 18 * s
    for count, label, action in ((add, "to add", "create"), (change, "to change", "update"), (destroy, "to destroy", "delete")):
        text = f"{SYMBOLS[action]} {count} {label}"
        w = small.getbbox(text)[2] + 20 * s
        d.rounded_rectangle((x, margin + 1 * s, x + w, margin + 25 * s), radius=12 * s,
                            fill=_mix(COLORS[action], 0.16), outline=_mix(COLORS[action], 0.7), width=max(1, s))
        d.text((x + 10 * s, margin + 5 * s), text, font=small, fill=INK)
        x += w + 8 * s
    if applied_through is not None:
        status = f"apply order · step {applied_through + 1} of {len(columns)}"
        d.text((width - margin - small.getbbox(status)[2], margin + 5 * s), status, font=small, fill=MUTED)

    # Boxes and step labels.
    boxes, x = {}, ox
    for w, col in enumerate(columns):
        label = f"step {w + 1}"
        live = applied_through is not None and w == applied_through
        d.text((x, oy - step_row), label, font=small, fill=INK if live else FAINT)
        offset = (tallest - len(col)) * (box_h + gap_y) / 2
        for i, a in enumerate(col):
            y = oy + offset + i * (box_h + gap_y)
            boxes[a] = (x, y, x + width_of[a], y + box_h)
        x += col_w[w] + gap_x

    def state(n: Node) -> str:
        if applied_through is None or n.action == "no-op":
            return "done"
        return "done" if n.wave < applied_through else "now" if n.wave == applied_through else "pending"

    for a, n in nodes.items():  # edges under the boxes
        for dep in n.deps:
            x0, y0 = boxes[dep][2], (boxes[dep][1] + boxes[dep][3]) / 2
            x1, y1 = boxes[a][0], (boxes[a][1] + boxes[a][3]) / 2
            bend = (x1 - x0) * 0.5
            pts = []
            for i in range(33):
                t = i / 32
                bx = (1 - t) ** 3 * x0 + 3 * (1 - t) ** 2 * t * (x0 + bend) + 3 * (1 - t) * t ** 2 * (x1 - bend) + t ** 3 * x1
                by = (1 - t) ** 3 * y0 + 3 * (1 - t) ** 2 * t * y0 + 3 * (1 - t) * t ** 2 * y1 + t ** 3 * y1
                pts.append((bx, by))
            lit = state(n) != "pending" and n.action != "no-op"
            d.line(pts, fill=_mix(COLORS[n.action], 0.5) if lit else EDGE, width=2 * s)

    for a, n in nodes.items():
        box = boxes[a]
        color, st = COLORS[n.action], state(n)
        quiet = n.action == "no-op"
        if st == "now":  # glow on the step being applied
            for grow, amt in ((9, 0.12), (5, 0.35)):
                d.rounded_rectangle((box[0] - grow * s, box[1] - grow * s, box[2] + grow * s, box[3] + grow * s),
                                    radius=(10 + grow) * s, outline=_mix(color, amt), width=2 * s)
        fill = _mix(color, 0.05 if quiet else 0.07 if st == "pending" else 0.20)
        outline = _mix(color, 0.45 if quiet else 0.35 if st == "pending" else 1.0)
        d.rounded_rectangle(box, radius=9 * s, fill=fill, outline=outline, width=2 * s)
        prefix, name = _split(a)
        dim = quiet or st == "pending"
        d.text((box[0] + pad_x, box[1] + 7 * s), prefix, font=type_font, fill=FAINT if dim else MUTED)
        label = f"{SYMBOLS[n.action]} {name}"
        d.text((box[0] + pad_x, box[1] + 21 * s), label, font=name_font, fill=MUTED if dim else INK)
        if n.action == "delete" and st == "done":
            sym_w = name_font.getbbox(f"{SYMBOLS[n.action]} ")[2]
            top, bottom = name_font.getbbox(label)[1], name_font.getbbox(label)[3]
            mid = box[1] + 21 * s + (top + bottom) / 2 + 1 * s  # through the middle of the letters
            d.line((box[0] + pad_x + sym_w, mid, box[0] + pad_x + name_font.getbbox(label)[2], mid),
                   fill=_mix(color, 0.9), width=2 * s)

    x, y = margin, img.height - margin - 14 * s  # legend: symbol + swatch + word, never color alone
    for action, word in (("create", "create"), ("update", "update"), ("replace", "replace"),
                         ("delete", "destroy"), ("no-op", "unchanged")):
        d.rounded_rectangle((x, y, x + 14 * s, y + 14 * s), radius=4 * s, fill=_mix(COLORS[action], 0.75))
        text = f"{SYMBOLS[action]} {word}"
        d.text((x + 20 * s, y - 1 * s), text, font=small, fill=MUTED)
        x += 20 * s + small.getbbox(text)[2] + 24 * s
    return img


def png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
