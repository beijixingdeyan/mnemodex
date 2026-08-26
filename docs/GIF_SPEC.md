# GIF Specification — `docs/demo.gif`

This document explains how the README demo GIF is generated, why it works
the way it does, and how to re-render it. It doubles as a spec for anyone
touching `mnemodex/gif.py`.

The demo must be *reproducible* — it should never drift from the real CLI —
and the project has a hard zero-dependency rule. So instead of Pillow or
ImageMagick, `mnemodex/gif.py` implements a from-scratch GIF89a encoder:
global color table, NETSCAPE2.0 loop, frame delays, variable-width LZW, a
5×7 bitmap font, and a tiny software renderer. The demo is a scripted
"terminal session" the encoder records frame by frame.

## Regenerating the demo

```sh
python -m mnemodex gif --out docs/demo.gif --frames N
```

- `--out` — output path (defaults to `docs/demo.gif`).
- `--frames N` — stop after *N* frames; `0` (default) renders the whole
  scripted session, one frame per typed chunk and per output line.
- `--width` / `--height` — canvas size (defaults to 860×460).
- `--fps` — playback speed (default 12); per-frame delay is `100 / fps`
  centiseconds.

Output is bytes-deterministic: the same arguments always produce the same
file (no randomness anywhere in the pipeline).

## The palette — 10 fixed colors

Every color the renderer draws comes from one canonical palette
(`FIXED_PALETTE` in `mnemodex/gif.py`):

| Name   | Hex       | RGB            |
| ------ | --------- | -------------- |
| BLACK  | `#0D1117` | `(13, 17, 23)`   |
| GREEN  | `#3FB950` | `(63, 185, 80)`  |
| BLUE   | `#58A6FF` | `(88, 166, 255)` |
| CYAN   | `#4CC6E2` | `(76, 198, 226)` |
| YELLOW | `#D29922` | `(210, 153, 34)` |
| RED    | `#F85149` | `(248, 81, 73)`  |
| PURPLE | `#BC8CFF` | `(188, 140, 255)` |
| GREY   | `#8B949E` | `(139, 148, 158)` |
| WHITE  | `#E6EDF3` | `(230, 237, 243)` |
| DIM    | `#484F58` | `(72, 79, 88)`   |

All frames share one **global color table**; there is no per-frame
quantization, and all ten colors survive in the final GIF.

## The 5×7 bitmap font

Text uses a public-domain classic 5×7 layout embedded in `mnemodex/gif.py`
(`_GLYPHS`): each glyph is 7 rows of 5-bit strings (`"01110"` = 5 pixels
wide), covering the printable ASCII range. Unknown characters fall back to
the `"?"` glyph (`DEFAULT_GLYPH`). Glyphs render at a `scale` derived from
the canvas width, with a 6-pixel advance per character.

## Frame model

The demo is a scripted session: a list of commands, each with output lines.

- **Partial-command typing** — each command is typed in chunks
  (`type_speed` characters per frame) with a blinking `▌` cursor, then a few
  blink frames on the full command, then it scrolls into the history.
- **Snapshot rendering** — every frame is a snapshot of the session state:
  the header bar, the visible window of completed lines, and the in-progress
  command line.
- **Snapshot diffing** — between consecutive frames **only the rows that
  changed are re-rendered**: the growing command line, the blinking cursor,
  or a newly appended output line. Prior state is carried forward, keeping
  re-renders cheap at any resolution.
- **Output lines** — appended one per frame; `--frames` can end the
  animation early, after which the final state is held.

## LZW variable-width codec

Pixel rows use classic GIF LZW (`_lzw_encode`), bit-exact for decoders:

- **Clear and EOI** — `clear = 1 << min_code_size`, `eoi = clear + 1`; the
  stream starts with clear and ends with EOI.
- **Code width growth** — encoding starts at `min_code_size + 1` bits; when
  the next dictionary code would exceed `1 << code_width`, the width grows by
  one bit, up to 12.
- **Dictionary reset** — at 4,096 codes the dictionary is flushed with a
  clear code and the width returns to `min_code_size + 1`.
- **Packing** — bits are emitted LSB-first, packed into bytes, and split
  into data sub-blocks of at most 255 bytes, terminated by a zero-length
  block.

## Why the palette must contain every drawn color

GIF indexes pixels into the color table; the encoder looks each drawn color
up in `FIXED_PALETTE` by exact value. A missing color would force per-frame
re-quantization (color drift) or a fallback — the nearest-neighbor fallback
(`_dist2`, squared Euclidean distance) exists so rendering never crashes on
a stray color, but it can visibly dull or shift an intended color. **Rule:
any new color a renderer change draws must be added to `FIXED_PALETTE`** —
keep the palette exhaustive and the demo crisp.

## Tips for re-rendering

- **Canvas size** — `--width`/`--height` adjust scale (clamped to
  `width // 640`, 1–3) and the visible history window automatically.
- **Playback** — lower `--fps` for a slower, more readable demo; raise it
  for a snappier loop.
- **File size** — `--frames N` cuts the animation early for a compressed
  README embed.
- **Determinism** — render twice and confirm identical bytes;
  `tests/test_gif.py` pins this (`test_deterministic` and the known-vector
  test).

After any change to the demo script or renderer, regenerate and commit the
updated `docs/demo.gif` alongside the code:

```sh
python -m mnemodex gif --out docs/demo.gif
```