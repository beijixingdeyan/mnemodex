"""A from-scratch GIF89a encoder — *and* the README demo generator.

Why does a code-memory tool ship its own GIF writer?

1. **Zero-dependency purity** — even the demo asset is produced by the
   project itself. No Pillow, no ImageMagick, no npm package.
2. **Reproducibility** — `mnemodex gif` regenerates `docs/demo.gif` from a
   scripted session, so the README demo never drifts from the real CLI.

This module implements:

* GIF89a container (global color table, NETSCAPE2.0 loop, frame delays),
* variable-width LZW compression (the classic GIF algorithm),
* a 5×7 bitmap font covering the printable ASCII range,
* a tiny software renderer (rects, text, bars) for the demo frames,
* `render_demo_gif()` — a scripted "terminal session" animation.
"""

from __future__ import annotations

import os
import struct
import time
from typing import Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# 5×7 bitmap font (public-domain classic layout), rows are strings of 5 bits
# ---------------------------------------------------------------------------

_GLYPHS: Dict[str, Tuple[str, ...]] = {
    " ": ("00000",) * 7,
    "!": ("00100", "00100", "00100", "00100", "00100", "00000", "00100"),
    '"': ("01010", "01010", "01010", "00000", "00000", "00000", "00000"),
    "#": ("01010", "01010", "11111", "01010", "11111", "01010", "01010"),
    "$": ("00100", "01111", "10100", "01110", "00101", "11110", "00100"),
    "%": ("11001", "11010", "00100", "00100", "01011", "10011", "00000"),
    "&": ("01100", "10010", "10100", "01100", "10101", "10010", "01101"),
    "'": ("00100", "00100", "00100", "00000", "00000", "00000", "00000"),
    "(": ("00010", "00100", "01000", "01000", "01000", "00100", "00010"),
    ")": ("01000", "00100", "00010", "00010", "00010", "00100", "01000"),
    "*": ("00000", "00100", "10101", "01110", "10101", "00100", "00000"),
    "+": ("00000", "00100", "00100", "11111", "00100", "00100", "00000"),
    ",": ("00000", "00000", "00000", "00000", "00110", "00100", "01000"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "00110", "00110"),
    "/": ("00001", "00010", "00010", "00100", "01000", "01000", "10000"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00110", "01000", "10000", "11111"),
    "3": ("11111", "00010", "00100", "00110", "00001", "10001", "01110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
    ":": ("00000", "00110", "00110", "00000", "00110", "00110", "00000"),
    ";": ("00000", "00110", "00110", "00000", "00110", "00100", "01000"),
    "<": ("00010", "00100", "01000", "10000", "01000", "00100", "00010"),
    "=": ("00000", "00000", "11111", "00000", "11111", "00000", "00000"),
    ">": ("01000", "00100", "00010", "00001", "00010", "00100", "01000"),
    "?": ("01110", "10001", "00001", "00110", "00100", "00000", "00100"),
    "@": ("01110", "10001", "00001", "01101", "10101", "10101", "01110"),
    "A": ("00100", "01010", "10001", "10001", "11111", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11100", "10010", "10001", "10001", "10001", "10010", "11100"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    "J": ("00111", "00010", "00010", "00010", "10010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "10001", "11001", "10101", "10011", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "[": ("01110", "01000", "01000", "01000", "01000", "01000", "01110"),
    "\\": ("10000", "10000", "01000", "00100", "00010", "00010", "00001"),
    "]": ("01110", "00010", "00010", "00010", "00010", "00010", "01110"),
    "^": ("00100", "01010", "10001", "00000", "00000", "00000", "00000"),
    "_": ("00000", "00000", "00000", "00000", "00000", "00000", "11111"),
    "`": ("01000", "00100", "00010", "00000", "00000", "00000", "00000"),
    "a": ("00000", "00000", "01110", "00001", "01111", "10001", "01111"),
    "b": ("10000", "10000", "10110", "11001", "10001", "10001", "11110"),
    "c": ("00000", "00000", "01110", "10000", "10000", "10001", "01110"),
    "d": ("00001", "00001", "01101", "10011", "10001", "10001", "01111"),
    "e": ("00000", "00000", "01110", "10001", "11111", "10000", "01110"),
    "f": ("00110", "01001", "01000", "11100", "01000", "01000", "01000"),
    "g": ("00000", "00000", "01111", "10001", "10001", "01111", "00001"),
    "h": ("10000", "10000", "10110", "11001", "10001", "10001", "10001"),
    "i": ("00100", "00000", "01100", "00100", "00100", "00100", "01110"),
    "j": ("00010", "00000", "00110", "00010", "00010", "10010", "01100"),
    "k": ("10000", "10000", "10010", "10100", "11000", "10100", "10010"),
    "l": ("01100", "00100", "00100", "00100", "00100", "00100", "01110"),
    "m": ("00000", "00000", "11010", "10101", "10101", "10001", "10001"),
    "n": ("00000", "00000", "10110", "11001", "10001", "10001", "10001"),
    "o": ("00000", "00000", "01110", "10001", "10001", "10001", "01110"),
    "p": ("00000", "00000", "11110", "10001", "10001", "11110", "10000"),
    "q": ("00000", "00000", "01101", "10011", "10001", "01111", "00001"),
    "r": ("00000", "00000", "10110", "11001", "10000", "10000", "10000"),
    "s": ("00000", "00000", "01111", "10000", "01110", "00001", "11110"),
    "t": ("01000", "01000", "11100", "01000", "01000", "01001", "00110"),
    "u": ("00000", "00000", "10001", "10001", "10001", "10011", "01101"),
    "v": ("00000", "00000", "10001", "10001", "10001", "01010", "00100"),
    "w": ("00000", "00000", "10001", "10001", "10101", "10101", "01010"),
    "x": ("00000", "00000", "10001", "01010", "00100", "01010", "10001"),
    "y": ("00000", "00000", "10001", "10001", "10001", "01111", "00001"),
    "z": ("00000", "00000", "11111", "00010", "00100", "01000", "11111"),
    "{": ("00010", "00100", "00100", "01000", "00100", "00100", "00010"),
    "|": ("00100", "00100", "00100", "00100", "00100", "00100", "00100"),
    "}": ("01000", "00100", "00100", "00010", "00100", "00100", "01000"),
    "~": ("00000", "00000", "01001", "10110", "00000", "00000", "00000"),
}

DEFAULT_GLYPH = _GLYPHS["?"]


def _glyph(ch: str) -> Tuple[str, ...]:
    return _GLYPHS.get(ch, DEFAULT_GLYPH)


# ---------------------------------------------------------------------------
# canvas / renderer
# ---------------------------------------------------------------------------

BLACK = (13, 17, 23)
GREEN = (63, 185, 80)
BLUE = (88, 166, 255)
CYAN = (76, 198, 226)
YELLOW = (210, 153, 34)
RED = (248, 81, 73)
PURPLE = (188, 140, 255)
GREY = (139, 148, 158)
WHITE = (230, 237, 243)
DIM = (72, 79, 88)


class Canvas:
    """RGB raster with tiny drawing primitives (rects + 5×7 text)."""

    def __init__(self, w: int, h: int, bg: Tuple[int, int, int] = BLACK):
        self.w = w
        self.h = h
        self.px: List[List[Tuple[int, int, int]]] = [[bg for _ in range(w)] for _ in range(h)]

    def rect(self, x: int, y: int, w: int, h: int, color: Tuple[int, int, int]) -> None:
        for yy in range(max(0, y), min(self.h, y + h)):
            row = self.px[yy]
            for xx in range(max(0, x), min(self.w, x + w)):
                row[xx] = color

    def hline(self, x: int, y: int, w: int, color: Tuple[int, int, int]) -> None:
        if 0 <= y < self.h:
            row = self.px[y]
            for xx in range(max(0, x), min(self.w, x + w)):
                row[xx] = color

    def vline(self, x: int, y: int, h: int, color: Tuple[int, int, int]) -> None:
        if 0 <= x < self.w:
            for yy in range(max(0, y), min(self.h, y + h)):
                self.px[yy][x] = color

    def text(self, x: int, y: int, s: str, color: Tuple[int, int, int], scale: int = 1) -> int:
        """Draw a string with the 5×7 font; returns the new x position."""
        for ch in s:
            if ch == "\n":
                continue
            glyph = _glyph(ch)
            for row, bits in enumerate(glyph):
                for col, bit in enumerate(bits):
                    if bit == "1":
                        self.rect(x + col * scale, y + row * scale, scale, scale, color)
            x += 6 * scale
        return x

    def bar(self, x: int, y: int, w: int, h: int, frac: float, color: Tuple[int, int, int]) -> None:
        self.rect(x, y, w, h, DIM)
        filled = int(w * max(0.0, min(1.0, frac)))
        if filled > 1:
            self.rect(x, y, filled, h, color)

    def to_indices(self) -> Tuple[List[int], List[Tuple[int, int, int]]]:
        """Flatten pixels to palette indices + palette (quantized if needed)."""
        flat: List[Tuple[int, int, int]] = [c for row in self.px for c in row]
        unique: List[Tuple[int, int, int]] = []
        lookup: Dict[Tuple[int, int, int], int] = {}
        for c in flat:
            if c not in lookup:
                lookup[c] = len(unique)
                unique.append(c)
        if len(unique) <= 256:
            return [lookup[c] for c in flat], unique
        # quantize: 4 levels per channel + 4 grays → fallback palette
        palette = [
            (r, g, b)
            for r in (51, 153, 221, 255)
            for g in (51, 153, 221, 255)
            for b in (51, 153, 221, 255)
        ] + [(r, r, r) for r in (0, 85, 170, 255)]
        idx_of: Dict[Tuple[int, int, int], int] = {}
        out: List[int] = []
        for c in flat:
            if c not in idx_of:
                idx_of[c] = min(range(len(palette)), key=lambda i: _dist2(c, palette[i]))
            out.append(idx_of[c])
        return out, palette


def _dist2(a: Tuple[int, int, int], b: Tuple[int, int, int]) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


# ---------------------------------------------------------------------------
# GIF LZW
# ---------------------------------------------------------------------------

def _lzw_encode(indices: Sequence[int], min_code_size: int) -> bytes:
    """GIF variable-width LZW, exactly as decoders expect (LSB-first bits)."""
    if not indices:
        # degenerate frame (all-empty image) — no pixel data to encode
        return b""
    clear = 1 << min_code_size
    eoi = clear + 1
    code_width = min_code_size + 1
    next_code = eoi + 1
    table: Dict[Tuple[int, ...], int] = {(i,): i for i in range(clear)}

    bits: List[int] = []

    def emit(code: int) -> None:
        for b in range(code_width):
            bits.append((code >> b) & 1)

    emit(clear)
    cur: Tuple[int, ...] = ()
    for idx in indices:
        nxt = cur + (idx,)
        if nxt in table:
            cur = nxt
        else:
            emit(table[cur])
            if next_code < 4096:
                table[nxt] = next_code
                next_code += 1
                if next_code > (1 << code_width) and code_width < 12:
                    code_width += 1
            cur = (idx,)
        if next_code >= 4096:
            emit(clear)
            code_width = min_code_size + 1
            next_code = eoi + 1
            table = {(i,): i for i in range(clear)}
    if cur:
        emit(table[cur])
    emit(eoi)

    # pack LSB-first bit stream into bytes
    out = bytearray()
    acc = 0
    nbits = 0
    for bit in bits:
        acc |= bit << nbits
        nbits += 1
        if nbits == 8:
            out.append(acc & 0xFF)
            acc = 0
            nbits = 0
    if nbits:
        out.append(acc & 0xFF)
    return bytes(out)


def _blockify(data: bytes) -> bytes:
    """GIF data sub-blocks: ≤255 byte chunks, 0x00 terminated."""
    out = bytearray()
    for i in range(0, len(data), 255):
        chunk = data[i : i + 255]
        out.append(len(chunk))
        out += chunk
    out.append(0x00)
    return bytes(out)


# ---------------------------------------------------------------------------
# GIF writer
# ---------------------------------------------------------------------------

def _gct(palette: List[Tuple[int, int, int]]) -> Tuple[int, bytes]:
    """Global color table; returns (size_bits, table_bytes)."""
    n = max(2, len(palette))
    size_bits = max(1, (n - 1).bit_length())
    table = bytearray()
    for i in range(1 << size_bits):
        if i < len(palette):
            table += bytes(palette[i])
        else:
            table += b"\x00\x00\x00"
    return size_bits, bytes(table)


class GifWriter:
    """Minimal animated GIF89a writer."""

    def __init__(self, width: int, height: int, loop: int = 0):
        self.width = width
        self.height = height
        self.loop = loop
        self.frames: List[Tuple[List[int], int, int, int]] = []  # (indices, delay_cs, offset_x, offset_y)

    def add_frame(self, indices: List[int], delay_cs: int = 8, offset_x: int = 0, offset_y: int = 0) -> None:
        self.frames.append((indices, max(1, delay_cs), offset_x, offset_y))

    def build(self, palette: List[Tuple[int, int, int]]) -> bytes:
        size_bits, gct_bytes = _gct(palette)
        packed = 0x80 | ((7 & 0x07) << 4) | (size_bits - 1)  # GCT present, 7-bit res, size
        out = bytearray(b"GIF89a")
        out += struct.pack("<HH", self.width, self.height)
        out.append(packed)
        out += b"\x00\x00"  # bg + aspect
        out += gct_bytes
        # NETSCAPE loop
        out += b"\x21\xff\x0bNETSCAPE2.0\x03\x01"
        out += struct.pack("<H", self.loop)
        out += b"\x00"
        min_code_size = max(2, size_bits)
        for indices, delay_cs, ox, oy in self.frames:
            # Graphic Control Extension
            out += b"\x21\xf9\x04\x04"  # disposal=2 (restore bg)
            out += struct.pack("<H", delay_cs)
            out += b"\x00\x00"
            # Image descriptor
            out += b"\x2c"
            out += struct.pack("<HHHH", ox, oy, self.width, self.height)
            out += b"\x00"
            out.append(min_code_size)
            out += _blockify(_lzw_encode(indices, min_code_size))
        out += b"\x3b"
        return bytes(out)


# ---------------------------------------------------------------------------
# demo renderer — a scripted terminal session
# ---------------------------------------------------------------------------

# Canonical palette: every color the renderer draws must appear here so the
# whole animation shares one global color table (no per-frame quantization).
FIXED_PALETTE: List[Tuple[int, int, int]] = [
    BLACK, GREEN, BLUE, CYAN, YELLOW, RED, PURPLE, GREY, WHITE, DIM,
]
_PAL_INDEX = {c: i for i, c in enumerate(FIXED_PALETTE)}

_CURSORS = ("▌", "▍", "▌")


def render_demo_gif(
    out_path: str,
    width: int = 860,
    height: int = 460,
    fps: int = 12,
    frames: int = 0,
) -> str:
    """Render the README demo GIF and write it to *out_path*."""
    delay_cs = max(1, int(100 / max(1, fps)))
    canvas = Canvas(width, height, BLACK)
    writer = GifWriter(width, height, loop=0)

    scale = max(1, min(3, width // 640))
    margin = 26
    line_h = 9 * scale
    x0 = margin
    y0 = 30 * scale
    header_h = 22 * scale
    max_lines = max(4, (height - y0 - header_h) // line_h - 1)

    completed: List[Tuple[str, Tuple[int, int, int]]] = []

    def snapshot(partial_cmd: Optional[str] = None, cursor: bool = False) -> None:
        """Clear, redraw header + session, add a frame."""
        canvas.rect(0, 0, width, height, BLACK)
        canvas.text(x0, 10 * scale, "mnemodex", GREEN, scale)
        canvas.text(x0 + 68 * scale, 10 * scale, "the memory index for AI coding agents", GREY, scale)
        canvas.hline(x0, 22 * scale, width - 2 * margin, DIM)
        y = y0
        for text, color in completed[-(max_lines - 1) :]:
            canvas.text(x0, y, text, color, scale)
            y += line_h
        if partial_cmd is not None:
            shown = partial_cmd + (_CURSORS[0] if cursor else " ")
            canvas.text(x0, y, shown, YELLOW, scale)
        # convert this frame to palette indices
        indices = []
        for row in canvas.px:
            for c in row:
                idx = _PAL_INDEX.get(c)
                if idx is None:
                    idx = min(range(len(FIXED_PALETTE)), key=lambda i: _dist2(c, FIXED_PALETTE[i]))
                indices.append(idx)
        writer.add_frame(indices, delay_cs)

    # ---- the scripted session ----
    commands = [
        ("$ mnemodex init",
         [("✓ store created at .mnemodex", GREEN), ("✓ .gitignore updated", GREEN)]),
        ("$ mnemodex index",
         [("indexed 1,284 files in 312 ms", GREEN),
          ("symbols 3,917 · edges 12,044 · languages 9", GREY)]),
        ('$ mnemodex add "auth tokens are cached for 5 min" --kind decision --tags cache',
         [("remembered decision ⚖  ab12cd34ef56", GREEN), ("cache · auth", GREY)]),
        ('$ mnemodex add "cookie hashes change per release — cache key pins schema" --kind gotcha',
         [("remembered gotcha ⚠  88ff00aa11bb", GREEN), ("cache · gotcha", GREY)]),
        ('$ mnemodex ask "cache eviction"',
         [("## Relevant memory", BLUE),
          ("[decision] auth tokens cached 5 min (repo, 2h ago)", GREY),
          ("[gotcha] cookie hashes pin cache key to schema (repo, 2h ago)", GREY),
          ("## Symbols", BLUE),
          ("- invalidate_cache (function) — src/cache/lru.py:41", GREY),
          ("- evict (method) — src/cache/lru.py:87", GREY),
          ("## Impact / dependents", BLUE),
          ("- src/api/auth.py imports src/cache/lru.py", GREY),
          ("context pack · 2,140 / 8,000 tokens ✓", GREEN)]),
        ("$ mnemodex serve",
         [("MCP server (stdio) ready", GREEN),
          ("→ connect Claude Code / Cursor / Codex (zero-dependency)", CYAN)]),
    ]

    frame_count = 0
    for cmd, out_lines in commands:
        # typing effect
        type_speed = max(2, len(cmd) // 45)  # chars per frame
        for i in range(1, len(cmd) + 1, type_speed):
            snapshot(partial_cmd=cmd[:i], cursor=True)
            frame_count += 1
        for k in range(4):  # blink on the full command
            snapshot(partial_cmd=cmd, cursor=(k % 2 == 0))
            frame_count += 1
        completed.append((cmd, YELLOW))
        if frames and frame_count >= frames:
            break
        # output lines
        for line, color in out_lines:
            completed.append((line, color))
            snapshot()
            frame_count += 1
            if frames and frame_count >= frames:
                break
    while frames and frame_count < frames:  # hold the final state
        snapshot(partial_cmd=cmd, cursor=(frame_count % 2 == 0))
        frame_count += 1

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "wb") as fh:
        fh.write(writer.build(FIXED_PALETTE))
    return out_path


if __name__ == "__main__":  # pragma: no cover
    import sys

    path = render_demo_gif(sys.argv[1] if len(sys.argv) > 1 else "docs/demo.gif")
    print(f"rendered {os.path.getsize(path)} bytes → {path}")