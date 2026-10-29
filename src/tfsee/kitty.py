"""Kitty graphics protocol: draw PNGs in terminals that support it (Ghostty, Kitty, WezTerm).

Spec: https://sw.kovidgoyal.net/kitty/graphics-protocol/
"""
from __future__ import annotations

import base64
import os

CHUNK = 4096  # payload bytes per escape sequence; must be a multiple of 4


def _command(control: str, payload: bytes = b"") -> str:
    """One graphics command, split into chunks: the first carries the control keys, the rest only m=."""
    data = base64.standard_b64encode(payload).decode()
    if not data:
        return f"\x1b_G{control}\x1b\\"
    chunks = [data[i:i + CHUNK] for i in range(0, len(data), CHUNK)]
    out = []
    for i, chunk in enumerate(chunks):
        more = 1 if i < len(chunks) - 1 else 0
        keys = f"{control},m={more}" if i == 0 else f"m={more}"
        out.append(f"\x1b_G{keys};{chunk}\x1b\\")
    return "".join(out)


def show(png: bytes, image_id: int, columns: int | None = None) -> str:
    """Transmit a PNG and place it at the cursor. q=2 keeps the terminal from replying."""
    fit = f",c={columns}" if columns else ""
    return _command(f"a=T,f=100,i={image_id},q=2{fit}", png)


def add_frame(png: bytes, image_id: int, gap_ms: int) -> str:
    """Append an animation frame (same size as the root image), shown for gap_ms."""
    return _command(f"a=f,f=100,i={image_id},z={gap_ms},q=2", png)


def set_gap(image_id: int, frame: int, gap_ms: int) -> str:
    return _command(f"a=a,i={image_id},r={frame},z={gap_ms},q=2")


def play(image_id: int, loops: int = 1) -> str:
    """Run the animation. loops=1 means forever; n>1 plays it n-1 times."""
    return _command(f"a=a,i={image_id},s=3,v={loops},q=2")


def delete(image_id: int) -> str:
    return _command(f"a=d,d=I,i={image_id},q=2")


def supported() -> bool:
    env = os.environ
    term = env.get("TERM", "")
    return bool(env.get("TERM_PROGRAM") in ("ghostty", "WezTerm") or "kitty" in term or "ghostty" in term
                or env.get("KITTY_WINDOW_ID") or env.get("GHOSTTY_RESOURCES_DIR")) and "TMUX" not in env


def native_animation() -> bool:
    """Ghostty added Kitty animation in 1.4; Kitty has had it for years. Older Ghostty gets redraws."""
    env = os.environ
    if env.get("TERM_PROGRAM") == "ghostty":
        version = env.get("TERM_PROGRAM_VERSION", "0").split("-")[0].split(".")
        try:
            return tuple(int(x) for x in version[:2]) >= (1, 4)
        except ValueError:
            return False
    return bool(env.get("KITTY_WINDOW_ID"))
