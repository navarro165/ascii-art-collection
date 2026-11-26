"""Render README images from the arts' own frame functions, so they match what a terminal shows.

Needs Pillow (dev group only). Run from the repo root:

    uv run --group dev python tools/make_images.py            # writes docs/images/*.png
    uv run --group dev python tools/make_images.py --sheet    # clownfish contact sheet, to pick a frame

No halo or glow is drawn: the tree defaults to glow 0, and the clownfish scene sends no background.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ascii_art.arts import clownfish, xmas_tree  # noqa: E402

REGULAR_FONTS = ("/System/Library/Fonts/Menlo.ttc", "DejaVuSansMono.ttf")
BOLD_FONTS = ("/System/Library/Fonts/Menlo.ttc", "DejaVuSansMono-Bold.ttf")
COLS, ROWS, ASPECT = 120, 40, 2.0
CELL_W, CELL_H = 10, 20
TREE_T = 28.0
CLOWNFISH_T = 6.0
_atlas = {}


def font(size, bold):
    for name in BOLD_FONTS if bold else REGULAR_FONTS:
        try:
            return ImageFont.truetype(name, size, index=1 if bold and name.endswith(".ttc") else 0)
        except OSError:
            continue
    raise OSError("no monospace font found")


def atlas(bold):
    """Alpha mask per glyph code (32 + i), drawn once per weight."""
    if bold not in _atlas:
        out = np.zeros((96, CELL_H, CELL_W), np.float32)
        f = font(int(CELL_H * 0.82), bold)
        for i in range(95):
            im = Image.new("L", (CELL_W, CELL_H), 0)
            ch = chr(32 + i)
            ImageDraw.Draw(im).text((0, -int(CELL_H * (0.26 if ch == "_" else 0.16))), ch, font=f, fill=255)
            out[i] = np.asarray(im, np.float32) / 255
        _atlas[bold] = out
    return _atlas[bold]


def paint(chars, ink, background, bold):
    rows, cols = chars.shape
    mask = atlas(bold)[chars - 32 if chars.min() >= 32 else np.maximum(chars - 32, 0)].transpose(0, 2, 1, 3).reshape(rows * CELL_H, cols * CELL_W)
    colour = np.repeat(np.repeat(ink.astype(np.float32), CELL_H, 0), CELL_W, 1)
    img = mask[..., None] * colour * 255 + (1 - mask[..., None]) * np.array(background, np.float32)
    return Image.fromarray(np.clip(img + 0.5, 0, 255).astype(np.uint8))


def clownfish_frame(t):
    clownfish.configure(COLS, ROWS, ASPECT)
    chars, ink = clownfish.grid(t)
    return paint(chars, ink, (0, 0, 0), bold=False)


def tree_frame(t):
    scene, asp = xmas_tree.scene_for(COLS, ROWS, ASPECT)
    chars, ink, _ = xmas_tree.render(scene, t, COLS, ROWS, asp, True, 0.0)
    return paint(chars, ink, xmas_tree.SKY_BG, bold=True)


def sheet(path):
    """Clownfish frames across its whole loop, thumbnailed, to choose a README frame by eye."""
    times = list(range(0, 22))
    thumbs = [clownfish_frame(float(t)).resize((COLS * CELL_W // 3, ROWS * CELL_H // 3)) for t in times]
    w, h = thumbs[0].size
    per_row = 4
    page = Image.new("RGB", (w * per_row, h * ((len(times) + per_row - 1) // per_row)))
    for i, im in enumerate(thumbs):
        ImageDraw.Draw(im).text((6, 4), f"t={times[i]}", fill=(255, 255, 0))
        page.paste(im, ((i % per_row) * w, (i // per_row) * h))
    page.save(path)
    print(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(ROOT / "docs" / "images"))
    parser.add_argument("--sheet", metavar="PNG", nargs="?", const="/tmp/clownfish-sheet.png", help="write a clownfish contact sheet instead")
    parser.add_argument("--clownfish-t", type=float, default=CLOWNFISH_T)
    parser.add_argument("--tree-t", type=float, default=TREE_T)
    args = parser.parse_args()
    if args.sheet:
        return sheet(args.sheet)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, im in (("clownfish", clownfish_frame(args.clownfish_t)), ("xmas-tree", tree_frame(args.tree_t))):
        im.save(out / f"{name}.png", optimize=False)
        print(out / f"{name}.png", im.size)


if __name__ == "__main__":
    main()
