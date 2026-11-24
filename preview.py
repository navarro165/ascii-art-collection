"""Headless previews of clownfish_term: render frames to PNG so the scene can be inspected.

Needs Pillow (preview only; the live renderer does not).
"""
import argparse
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import clownfish_term as ct

FONT_PATHS = ("/System/Library/Fonts/Menlo.ttc", "DejaVuSansMono.ttf")
_atlas = {}


def font(size):
    for name in FONT_PATHS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    raise OSError("no monospace font found")


def atlas(cw, ch):
    if (cw, ch) not in _atlas:
        out = np.zeros((96, ch, cw), np.float32)
        f = font(int(ch * 0.82))
        for i in range(95):
            im = Image.new("L", (cw, ch), 0)
            ImageDraw.Draw(im).text((0, -int(ch * 0.16) if chr(32 + i) != "_" else -int(ch * 0.26)), chr(32 + i), font=f, fill=255)
            out[i] = np.asarray(im, np.float32) / 255
        _atlas[(cw, ch)] = out
    return _atlas[(cw, ch)]


def paint(chars, ink, cw=12, ch=24, glow=True):
    rows, cols = chars.shape
    mask = atlas(cw, ch)[chars].transpose(0, 2, 1, 3).reshape(rows * ch, cols * cw)
    col = np.repeat(np.repeat(ink.astype(np.float32), ch, 0), cw, 1)
    img = mask[..., None] * col
    if glow:
        small = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).resize((cols * cw // 4, rows * ch // 4), Image.BOX)
        near = np.asarray(small.filter(ImageFilter.GaussianBlur(2.2)).resize((cols * cw, rows * ch), Image.BILINEAR), np.float32)
        img = img * 255 + 0.5 * near
    else:
        img = img * 255
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


def render(cols, rows, aspect, t):
    ct.configure(cols, rows, aspect)
    chars, ink = ct.grid(t)
    return paint(chars, ink, 12, int(12 * aspect))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--size", default="120x40")
    p.add_argument("--aspect", type=float, default=2.0)
    p.add_argument("--t", type=float, nargs="+", default=[3.0])
    p.add_argument("--out", default="/tmp/clownfish-preview")
    a = p.parse_args()
    cols, rows = map(int, a.size.split("x"))
    os.makedirs(a.out, exist_ok=True)
    for t in a.t:
        path = f"{a.out}/{cols}x{rows}_t{t:g}.png"
        render(cols, rows, a.aspect, t).save(path)
        print(path)


if __name__ == "__main__":
    main()
