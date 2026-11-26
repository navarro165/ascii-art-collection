#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy"]
# ///
"""Live terminal ASCII Christmas tree, v2.

Ported from christmas_tree.py in jaeyonni/XMasTree (https://github.com/jaeyonni/XMasTree), a recreation of the
"ASCII Christmas Tree" reel by dwcminh.ascii (https://www.instagram.com/reels/DfoWsojSWA2/). The tree is a 3D
point cloud projected onto a character grid; this version draws it into the terminal at any size. Terminal
port by navarro165. No licence upstream; see the README. Press any key to quit.
"""
import argparse
import atexit
import fcntl
import math
import os
import select
import signal
import struct
import sys
import termios
import time
import tty

import numpy as np


# timing & layout constants
TAU = 2.0 * np.pi
GROUND = -1.05
Y0 = -0.74
Y1 = 1.42
ROT_SPEED = 0.31

T_GROW = (1.0, 5.5)
T_GARLAND = (6.3, 7.8)
T_BALLS = (7.5, 9.5)
T_LIGHTS = (8.1, 11.4)
T_PRESENTS = (10.0, 11.1)
T_STAR = 11.6
T_MSG = 13.0

MESSAGE = "M E R R Y   C H R I S T M A S   2 0 2 6"

# colors (HDR linear float RGB)
WHITE = (1.0, 1.0, 1.0)
GOLD = (1.0, 0.90, 0.28)
RED = (1.0, 0.24, 0.26)
BAUBLE_GOLD = (1.0, 0.85, 0.26)
BLUE = (0.34, 0.50, 1.00)
GREEN_BOX = (0.30, 0.90, 0.40)
SILVER = (0.93, 0.95, 1.00)
WARM = (1.0, 0.92, 0.58)
TRUNK_COL = (0.64, 0.34, 0.22)
SKY_BG = (9, 10, 16)

# material IDs & per-material ASCII brightness ramps
NEEDLE, SNOW, INNER, TRUNK, TINSEL, BALL, LIGHT, BOX, RIBBON = range(9)
RAMPS = {
    NEEDLE: ".-;~^vx%&W#",
    SNOW:   ".+*#",
    INNER:  ".-~vx%&",
    TRUNK:  ":|=#",
    TINSEL: "-~=*#@",
    BALL:   ".:o0O%#@",
    LIGHT:  ".+*#@",
    BOX:    ".:-=+xX%%#",
    RIBBON: ".-+=*##",
}
RAMP_ARRS = [np.array([ord(c) for c in RAMPS[m]], dtype=np.int32) for m in range(9)]

# how much of each material's ink spills into the background glow (needle .. ribbon)
GLOW_DEFAULT = 0.0                                    # background-colour glow strength: 0 off (default), 1 the original heavy halo
EMIS = np.array([0.10, 0.10, 0.06, 0.0, 0.40, 0.30, 0.55, 0.15, 0.20], dtype=np.float32)
SKY_TOP = np.array([2, 4, 9], dtype=np.float32) / 255
SKY_HORIZON = np.array([10, 16, 28], dtype=np.float32) / 255


def unit(v):
    """Normalize vector(s) along the last axis."""
    v = np.asarray(v, dtype=np.float64)
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.maximum(n, 1e-8)


def smooth(x):
    """Cubic Hermite smoothstep clamped to [0, 1]."""
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def envelope(y):
    """Outer radial envelope of the spruce tree cone at height y."""
    u = np.clip((y - Y0) / (Y1 - Y0), 0.0, 1.0)
    return 0.94 * (1.0 - u) ** 0.94 + 0.04


def fib_sphere(n):
    """Distribute n unit points quasi-uniformly on a unit sphere."""
    i = np.arange(n, dtype=np.float64) + 0.5
    phi = np.arccos(1.0 - 2.0 * i / n)
    theta = np.pi * (1.0 + 5.0 ** 0.5) * i
    sp = np.sin(phi)
    return np.stack([sp * np.cos(theta), np.cos(phi), sp * np.sin(theta)], axis=1)


class Parts:
    """Accumulator for 3D point cloud geometry and animation metadata."""

    def __init__(self):
        self.pos = []
        self.nrm = []
        self.col = []
        self.mat = []
        self.t0 = []
        self.base = []
        self.phase = []
        self.centre = []
        self.pop = []
        self.bias = []

    def add(self, p, nrm, col, mat, t0, base=1.0, phase=0.0, centre=None, pop=False, bias=0.0):
        p = np.asarray(p, dtype=np.float64)
        n = len(p)
        nrm = unit(np.broadcast_to(nrm, (n, 3)))
        col = np.broadcast_to(np.asarray(col, dtype=np.float64), (n, 3))
        mat = np.broadcast_to(np.asarray(mat, dtype=np.int32), (n,))
        t0 = np.broadcast_to(np.asarray(t0, dtype=np.float64), (n,))
        base = np.broadcast_to(np.asarray(base, dtype=np.float64), (n,))
        phase = np.broadcast_to(np.asarray(phase, dtype=np.float64), (n,))
        bias = np.broadcast_to(np.asarray(bias, dtype=np.float64), (n,))
        centre_arr = p if centre is None else np.broadcast_to(np.asarray(centre, dtype=np.float64), (n, 3))
        pop_arr = np.full(n, bool(pop), dtype=bool)

        self.pos.append(p)
        self.nrm.append(nrm)
        self.col.append(col)
        self.mat.append(mat)
        self.t0.append(t0)
        self.base.append(base)
        self.phase.append(phase)
        self.centre.append(centre_arr)
        self.pop.append(pop_arr)
        self.bias.append(bias)

    def compile(self):
        """Pack accumulated point lists into contiguous float32/int32 NumPy arrays."""
        return {
            "pos": np.concatenate(self.pos, axis=0).astype(np.float32),
            "nrm": np.concatenate(self.nrm, axis=0).astype(np.float32),
            "col": np.concatenate(self.col, axis=0).astype(np.float32),
            "mat": np.concatenate(self.mat, axis=0).astype(np.int32),
            "t0": np.concatenate(self.t0, axis=0).astype(np.float32),
            "base": np.concatenate(self.base, axis=0).astype(np.float32),
            "phase": np.concatenate(self.phase, axis=0).astype(np.float32),
            "centre": np.concatenate(self.centre, axis=0).astype(np.float32),
            "pop": np.concatenate(self.pop, axis=0),
            "bias": np.concatenate(self.bias, axis=0).astype(np.float32),
        }


def grow_time(y):
    return T_GROW[0] + (T_GROW[1] - T_GROW[0]) * np.clip((y - GROUND) / (Y1 - GROUND), 0, 1)


def build(density=1.0):
    rng = np.random.default_rng(7)
    rng_fx = np.random.default_rng(11)                         # effects only, keeps the geometry stream intact
    q = Parts()
    tips = []

    # needles: whorls of drooping branches, denser and longer at the bottom
    for i, y in enumerate(np.linspace(Y0 + 0.04, Y1 - 0.05, 21)):
        u = (y - Y0) / (Y1 - Y0)
        R = envelope(y) + 0.04
        nb = int(5 + 10 * (1 - u))
        for b in range(nb):
            a = TAU * (b + 0.5 * rng.random()) / nb + i * 0.77
            L = R * rng.uniform(0.76, 1.12)
            n = int((20 + 165 * L) * density)
            s = rng.random(n) ** 0.65                               # 0 trunk .. 1 tip
            d = np.array([np.cos(a), 0, np.sin(a)])
            side = np.array([-np.sin(a), 0, np.cos(a)])
            spread = (0.022 + 0.085 * s) * rng.normal(0, 1, n)
            sl = s * L
            p = d * sl[:, None] + side * spread[:, None]
            p[:, 1] = y + 0.05 * sl - 0.18 * sl ** 2 + 0.012 * rng.normal(0, 1, n)
            nrm = unit(d * 0.75 + np.array([0, 0.55, 0]) + 0.3 * rng.normal(0, 1, (n, 3)))
            ao = (0.30 + 0.70 * s ** 1.3) * rng.uniform(0.75, 1.1, n)
            snow = (s > 0.5) & (rng.random(n) < 0.06 * s) & (nrm[:, 1] > 0.5)
            green = np.array([0.05, 0.42, 0.20]) + np.array([0.10, 0.38, 0.20]) * s[:, None]   # emerald, like the reel
            t_spawn = grow_time(y) + 0.35 * s + 0.22 * rng.random(n)
            q.add(p, nrm, np.where(snow[:, None], WHITE, green), np.where(snow, SNOW, NEEDLE),
                  t_spawn, base=np.where(snow, 1.0, ao), phase=rng_fx.random(n) * TAU)
            tl = 0.93 * L
            tips.append(d * tl + [0, y + 0.05 * tl - 0.18 * tl ** 2, 0])

    # dark inner cone so nothing shows through the branches
    m = int(2800 * density)
    y = Y0 + (Y1 - 0.1 - Y0) * rng.random(m)
    phi = rng.random(m) * TAU
    out = np.stack([np.cos(phi), np.full(m, 0.3), np.sin(phi)], 1)
    r = 0.56 * envelope(y)
    q.add(np.stack([np.cos(phi) * r, y, np.sin(phi) * r], 1), out, (0.05, 0.34, 0.18), INNER,
          grow_time(y), base=0.70)

    # trunk
    m = int(900 * density)
    y, phi = GROUND + rng.random(m) * (Y0 + 0.14 - GROUND), rng.random(m) * TAU
    n = np.stack([np.cos(phi), np.zeros(m), np.sin(phi)], 1)
    bark = 0.80 + 0.20 * np.sign(np.sin(phi * 30 + y * 5))
    q.add(n * 0.095 + np.stack([np.zeros(m), y, np.zeros(m)], 1), n, np.array(TRUNK_COL) * bark[:, None],
          TRUNK, grow_time(y), bias=0.01)

    # tinsel garland: delicate gold spiral drooping in swags between hanging points
    u = np.linspace(0, 1, int(950 * density))
    turns = 4.1
    yg = Y0 + 0.14 + (Y1 - Y0 - 0.40) * u
    ag = TAU * turns * u + 0.9
    swag = -0.055 * np.abs(np.sin(ag * 2.5))
    rg = envelope(yg) + 0.025
    line = np.stack([np.cos(ag) * rg, yg + swag, np.sin(ag) * rg], 1)
    for _ in range(2):
        nrm = np.stack([np.cos(ag), np.full_like(u, 0.3), np.sin(ag)], 1) + 0.5 * rng.normal(0, 1, line.shape)
        q.add(line + 0.005 * rng.normal(0, 1, line.shape), nrm, GOLD, TINSEL,
              T_GARLAND[0] + u * (T_GARLAND[1] - T_GARLAND[0]), phase=rng.random(len(u)) * TAU, bias=0.025)

    # baubles: red and gold spheres tucked onto branches
    sphere = fib_sphere(int(90 * density))
    for k in range(34):
        u = (k + rng.random()) / 34
        y = Y0 + 0.08 + u * (Y1 - Y0 - 0.38)
        a = k * 2.39996 + rng.random() * 0.4
        c = np.array([np.cos(a), 0, np.sin(a)]) * (envelope(y) + 0.02) + [0, y - 0.03, 0]
        rad = 0.058 + 0.028 * (1 - u)
        col = RED if k % 2 == 0 else BAUBLE_GOLD             # half red, half gold
        q.add(c + sphere * rad, sphere, col, BALL, T_BALLS[0] + rng.random() * (T_BALLS[1] - T_BALLS[0]),
              centre=c, pop=True, bias=0.05)

    # fairy lights on the branch tips
    tips = np.array(tips)
    pick = rng.choice(len(tips), min(170, len(tips)), replace=False)
    bulb = fib_sphere(12)
    light_t0 = T_LIGHTS[0] + rng.random(len(pick)) * (T_LIGHTS[1] - T_LIGHTS[0])
    for c, t0 in zip(tips[pick], light_t0):
        col = WARM if rng.random() < 0.8 else (1.0, 0.95, 0.85)
        q.add(c + bulb * 0.030, bulb, col, LIGHT, t0, centre=c, phase=rng.random() * TAU, bias=0.07)

    # presents: boxes with a crossed ribbon and a bow
    gifts = [
        (0.3, 1.12, 0.30, 0.24, 0.28, 0.4, RED, GOLD),
        (1.5, 1.18, 0.26, 0.30, 0.24, 0.9, BLUE, GOLD),
        (2.6, 1.10, 0.34, 0.18, 0.26, 1.0, GOLD, RED),
        (3.7, 1.18, 0.24, 0.26, 0.24, 0.6, SILVER, RED),
        (4.7, 1.12, 0.30, 0.22, 0.30, 0.1, GREEN_BOX, RED),
        (5.6, 1.22, 0.22, 0.26, 0.22, 0.7, RED, SILVER),
    ]
    loop = fib_sphere(48)
    for g, (a, dist, w, h, d, rot, body, rib) in enumerate(gifts):
        areas = np.array([w * d, h * d, h * d, h * w, h * w])
        m = int(2600 * areas.sum() * density)
        face = rng.choice(5, m, p=areas / areas.sum())
        fa, fb = rng.random(m) - 0.5, rng.random(m) - 0.5
        lx = np.select([face == 0, face == 1, face == 2], [fa * w, np.full(m, w * 0.5), np.full(m, -w * 0.5)], fa * w)   # fa, not fb: fb also drives ly
        ly = np.where(face == 0, h, (fb + 0.5) * h)
        lz = np.select([face == 0, face <= 2, face == 3], [fb * d, fa * d, np.full(m, d * 0.5)], np.full(m, -d * 0.5))
        n = np.array([[0, 1, 0], [1, 0, 0], [-1, 0, 0], [0, 0, 1], [0, 0, -1.0]])[face]
        on_x, on_z = np.abs(lx) < 0.022, np.abs(lz) < 0.022
        ribbon = np.select([face == 0, face <= 2], [on_x | on_z, on_z], on_x)

        # bow on top of the present
        bow_pts = []
        bow_nrm = []
        for ang in (0.4, -0.4, np.pi + 0.4, np.pi - 0.4):
            ca, sa = np.cos(ang), np.sin(ang)
            lp = loop * [0.034, 0.020, 0.015] + [0.034, 0.014, 0.0]
            rx_l = lp[:, 0] * ca - lp[:, 2] * sa
            rz_l = lp[:, 0] * sa + lp[:, 2] * ca
            bow_pts.append(np.stack([rx_l, h + lp[:, 1], rz_l], 1))
            bnx = loop[:, 0] * ca - loop[:, 2] * sa
            bnz = loop[:, 0] * sa + loop[:, 2] * ca
            bow_nrm.append(np.stack([bnx, loop[:, 1], bnz], 1))
        bow_pts.append(loop * [0.020, 0.018, 0.020] + [0.0, h + 0.010, 0.0])
        bow_nrm.append(loop)
        bow = np.concatenate(bow_pts, 0)
        bn = np.concatenate(bow_nrm, 0)

        pts_local = np.concatenate([np.stack([lx, ly, lz], 1) + n * np.where(ribbon, 0.006, 0.0)[:, None], bow], 0)
        nrm_local = np.concatenate([n, bn], 0)
        is_rib = np.concatenate([ribbon, np.ones(len(bow), dtype=bool)])
        cols = np.where(is_rib[:, None], rib, body)
        mats = np.where(is_rib, RIBBON, BOX)
        biases = np.where(is_rib, 0.035, 0.0)

        cr, sr = np.cos(rot), np.sin(rot)
        center_world = np.array([np.cos(a) * dist, GROUND, np.sin(a) * dist])
        px_w = pts_local[:, 0] * cr - pts_local[:, 2] * sr + center_world[0]
        py_w = pts_local[:, 1] + GROUND
        pz_w = pts_local[:, 0] * sr + pts_local[:, 2] * cr + center_world[2]
        nx_w = nrm_local[:, 0] * cr - nrm_local[:, 2] * sr
        ny_w = nrm_local[:, 1]
        nz_w = nrm_local[:, 0] * sr + nrm_local[:, 2] * cr
        t_gift = T_PRESENTS[0] + (T_PRESENTS[1] - T_PRESENTS[0]) * (g / max(len(gifts) - 1, 1))
        pop_center = center_world + np.array([0.0, h * 0.5, 0.0])
        q.add(
            np.stack([px_w, py_w, pz_w], 1),
            np.stack([nx_w, ny_w, nz_w], 1),
            cols,
            mats,
            t_gift,
            centre=pop_center,
            pop=True,
            bias=biases,
        )

    data = q.compile()
    data["light_t0"] = np.sort(light_t0).astype(np.float32)
    data["dith"] = (rng_fx.random(len(data["t0"])) - 0.5).astype(np.float32)   # per-point glyph jitter
    return data


ASPECT0 = 9 / 14                                     # cell width/height the scene was tuned for (88 x 74 cells)


def view_scales(cols, rows, aspect):
    """Horizontal and vertical projection scales, plus the zoom k, for a grid of cols x rows cells.

    `aspect` is cell width over height. The tree is pinned to the short axis of the terminal, so a
    bigger or wider window shows the same tree with more cells (more detail), not a bigger one.
    """
    k = min(cols / 88.0, rows / aspect / (74 / ASPECT0))
    return 90.0 * k / ASPECT0, 90.0 * k * aspect / ASPECT0, k


def project(pts, cols, rows, aspect):
    """Perspective projection from rotated world space onto ASCII grid coordinates."""
    sx, sy, _ = view_scales(cols, rows, aspect)
    d = np.maximum(5.0 - pts[:, 2], 0.2)
    x = cols * 0.5 + sx * pts[:, 0] / d
    y = rows * 0.53 - sy * pts[:, 1] / d
    return x, y, d


def put(char, col, y, x, ch, tint, power):
    """Write a single character and HDR color into cell buffers."""
    if 0 <= y < char.shape[0] and 0 <= x < char.shape[1]:
        char[y, x] = ord(ch)
        col[y, x] = np.asarray(tint, dtype=np.float32) * float(power)


def point_in_poly(px, py, poly):
    res = np.zeros_like(px, dtype=bool)
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % len(poly)]
        res ^= ((y1 > py) != (y2 > py)) & (px < (x2 - x1) * (py - y1) / (y2 - y1) + x1)
    return res


def star(char, col, cx, cy, size, t, power, cell, flash=0.0):
    # thin rays first, then a filled five-pointed star on top;
    # when it lights up it bursts white with long rays, then settles to gold
    tint = np.array(GOLD) + (1 - np.array(GOLD)) * flash
    power = power * (1 + 1.6 * flash)
    for k in range(8):
        ang = k * TAU / 8 + 0.10 * np.sin(t * 0.7)
        if np.sin(ang) < -0.3:                                  # no rays down into tree
            continue
        reach = size * (3.0 + 0.8 * np.sin(t * 3 + k * 1.3)) * (1.0 if k % 2 == 0 else 0.7)
        ch = "-|/\\"[ [0, 2, 1, 3][int(round((np.degrees(ang) % 180) / 45)) % 4] ]
        for s in np.arange(size * 1.0, reach, 0.5):
            y, x = int(round(cy - np.sin(ang) * s * cell / ASPECT0)), int(round(cx + np.cos(ang) * s))
            if 0 <= y < char.shape[0] and 0 <= x < char.shape[1] and col[y, x].max() < 0.38:
                put(char, col, y, x, ch, tint, power * 0.55 * (1.0 - 0.72 * s / reach))

    # filled 5-pointed star polygon with 2x2 sub-cell coverage for crisp silhouette tips
    outer = size * 1.05
    inner = outer * 0.46
    vy_scale = cell * 1.05
    poly = []
    for k in range(10):
        ang = -np.pi * 0.5 + k * np.pi / 5.0
        r = outer if k % 2 == 0 else inner
        poly.append((cx + np.cos(ang) * r, cy + np.sin(ang) * r * vy_scale))

    rx = int(math.ceil(outer + 1))
    ry = int(math.ceil(outer * vy_scale + 1))
    x_lo, x_hi = max(0, cx - rx), min(char.shape[1], cx + rx + 1)
    y_lo, y_hi = max(0, cy - ry), min(char.shape[0], cy + ry + 1)
    if x_lo >= x_hi or y_lo >= y_hi:
        return

    gy, gx = np.mgrid[y_lo:y_hi, x_lo:x_hi]
    gx_f, gy_f = gx.astype(np.float64), gy.astype(np.float64)
    cov = np.zeros_like(gx_f)
    for ox in (-0.22, 0.22):
        for oy in (-0.22, 0.22):
            cov += point_in_poly(gx_f + ox, gy_f + oy, poly)
    cov *= 0.25

    ys, xs, cv = gy[cov > 0], gx[cov > 0], cov[cov > 0]
    dist = np.hypot(xs - cx, (ys - cy) / max(vy_scale, 1e-6)) / max(outer, 1e-6)
    lum = power * np.clip((1.05 - 0.50 * dist) * (0.45 + 0.55 * cv), 0.35, 1.15)
    for py_i, px_i, lv, c_frac in zip(ys, xs, lum, cv):
        if c_frac >= 0.99 and lv > 0.72:
            ch = "@"
        elif lv > 0.52 and c_frac >= 0.5:
            ch = "#"
        else:
            ch = "*"
        put(char, col, int(py_i), int(px_i), ch, tint, float(lv))


def _make_background_cache(cols, rows, aspect):
    """Precompute static snow ground plane and deterministic snowfall flakes."""
    rng = np.random.default_rng(123)
    sx, sy, _ = view_scales(cols, rows, aspect)
    ground_char = np.zeros((rows, cols), dtype=np.int32)
    ground_col = np.zeros((rows, cols, 3), dtype=np.float32)

    sky_h = rows * 0.525
    horizon = int(math.floor(sky_h))
    for r in range(horizon, rows):
        dr = (r + 0.45) - sky_h
        if dr <= 0.15:
            continue
        d = sy * (-GROUND) / dr
        fade = 1.0 / (1.0 + 0.014 * d * d)
        row_prob = 0.97 if r >= horizon + 2 else (0.55 if r == horizon + 1 else 0.32)
        for c in range(cols):
            if rng.random() > row_prob:
                continue
            wx = (c - cols * 0.5) * d / sx
            wz = 5.0 - d
            rad2 = wx * wx + wz * wz
            pool = 0.08 * math.exp(-rad2 / 4.0)
            n = rng.random()
            val = (0.08 + 0.095 * fade + pool) * (0.78 + 0.44 * n)
            if val > 0.215 and n > 0.78:
                ch = ord("=")
            elif val > 0.135 and n > 0.42:
                ch = ord("-")
            else:
                ch = ord(".")
            ground_char[r, c] = ch
            ground_col[r, c] = np.array([0.74, 0.76, 1.0], dtype=np.float32) * val

    # three snow layers for parallax: far flakes are small, dim and slow; near ones big, bright, fast
    # and drawn in front of the tree
    n_snow = max(60, int(175 * cols * rows / 6512))
    layer = rng.choice(3, n_snow, p=[0.45, 0.40, 0.15])
    pick = lambda lo, hi: np.array(lo)[layer] + (np.array(hi) - np.array(lo))[layer] * rng.random(n_snow)
    snow = {
        "x0": rng.uniform(0, cols, n_snow),
        "y0": rng.uniform(0, rows, n_snow),
        "vy": pick([2.0, 4.5, 9.0], [3.5, 7.0, 13.0]),
        "phase": rng.uniform(0, TAU, n_snow),
        "sway": pick([0.2, 0.4, 0.9], [0.5, 1.0, 1.9]),
        "glyph": np.array([ord("."), ord("+"), ord("*")])[layer],
        "bright": pick([0.26, 0.55, 0.86], [0.42, 0.78, 1.0]),
        "near": layer == 2,
    }
    gy, gx = np.nonzero(ground_char)
    # about 1 in 5 ground cells can sparkle, each for ~0.2 s once every 4-10 s
    sparkle = {"y": gy, "x": gx, "phase": rng.random(len(gy)), "rate": rng.uniform(0.1, 0.25, len(gy)),
               "live": rng.random(len(gy)) < 0.2}
    return ground_char, ground_col, snow, sparkle


_BG_CACHE = {}


def box_blur(a, rx, ry):
    """Separable box blur of a (rows, cols, 3) array with edge clamping, via cumulative sums."""
    for axis, r in ((1, rx), (0, ry)):
        if r <= 0:
            continue
        pad = [(0, 0)] * a.ndim
        pad[axis] = (r + 1, r)
        c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis)
        n = a.shape[axis]
        hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
        lo = np.take(c, np.arange(0, n), axis=axis)
        a = (hi - lo) / (2 * r + 1)
    return a


def shift_or(m, dy, dx):
    """m OR-ed with copies of itself shifted by up to dy rows and dx columns (a cheap dilation)."""
    out = m.copy()
    for oy in range(-dy, dy + 1):
        for ox in range(-dx, dx + 1):
            if oy or ox:
                out |= np.roll(np.roll(m, oy, 0), ox, 1)
    return out


def tone_map(c):
    """Hue-preserving highlight roll-off: HDR ink above 1.0 saturates toward a white core instead of clipping."""
    m = np.maximum(c.max(axis=-1, keepdims=True), 1e-6)
    base = c / np.maximum(m, 1.0)
    w = np.clip((m - 1.0) * 0.45, 0.0, 0.6)
    return base + (1.0 - base) * w


def render(scene, t, cols, rows, aspect, hud=True, glow=GLOW_DEFAULT):
    """Render one frame of the ASCII Christmas tree at timestamp t."""
    key = (cols, rows, round(aspect, 5))
    if key not in _BG_CACHE:
        _BG_CACHE[key] = _make_background_cache(cols, rows, aspect)
    ground_char, ground_col, snow, sparkle = _BG_CACHE[key]

    char = ground_char.copy()
    col = ground_col.copy()

    # snow crystals on the ground catch the light for a moment
    tw = sparkle["live"] & (np.mod(t * sparkle["rate"] + sparkle["phase"], 1.0) < 0.03)
    char[sparkle["y"][tw], sparkle["x"][tw]] = ord("*")
    col[sparkle["y"][tw], sparkle["x"][tw]] = (0.62, 0.68, 0.85)

    # far and mid snowfall drift behind the tree; the near layer is drawn over it further down
    sx = np.mod((snow["x0"] + snow["sway"] * np.sin(t * 1.1 + snow["phase"])).round().astype(np.int32), cols)
    sy = np.mod((snow["y0"] + snow["vy"] * t).round().astype(np.int32), rows)
    snow_mask = (col[sy, sx].max(axis=1) < snow["bright"]) & ~snow["near"]
    if np.any(snow_mask):
        sy_m, sx_m = sy[snow_mask], sx[snow_mask]
        char[sy_m, sx_m] = snow["glyph"][snow_mask]
        col[sy_m, sx_m] = snow["bright"][snow_mask, None]

    # filter points already spawned at time t
    t0 = scene["t0"]
    mask = t >= t0
    rot = ROT_SPEED * t
    info = {
        "rot_deg": float(np.degrees(rot) % 360.0),
        "lights": int(np.searchsorted(scene["light_t0"], t, side="right")),
    }

    emis = np.zeros((rows, cols), dtype=np.float32)
    tree = np.zeros((rows, cols), dtype=bool)
    if np.any(mask):
        # once everything has spawned (most of the show) skip the per-frame gather copies
        pick = (lambda a: a) if mask.all() else (lambda a: a[mask])
        pos = pick(scene["pos"])
        nrm = pick(scene["nrm"])
        pcol = pick(scene["col"])
        mat = pick(scene["mat"])
        age = t - pick(t0)
        base = pick(scene["base"])
        phase = pick(scene["phase"])
        pop = pick(scene["pop"])
        bias = pick(scene["bias"])
        dith = pick(scene["dith"])

        # pop-in scaling from local part centre
        popping = np.flatnonzero(pop & (age < 0.25))
        if len(popping):
            centre = pick(scene["centre"])[popping]
            pos = pos.copy()
            pos[popping] = centre + (pos[popping] - centre) * smooth(age[popping] / 0.25)[:, None]

        # rotate scene around Y axis
        c, s = math.cos(rot), math.sin(rot)
        rx = pos[:, 0] * c + pos[:, 2] * s
        rz = -pos[:, 0] * s + pos[:, 2] * c
        rpos = np.stack([rx, pos[:, 1], rz], axis=1)

        nx = nrm[:, 0] * c + nrm[:, 2] * s
        ny = nrm[:, 1]
        nz = -nrm[:, 0] * s + nrm[:, 2] * c

        # lighting (warm front-left directional key + rich ambient floor)
        ndotl = np.clip(-0.34 * nx + 0.45 * ny + 0.82 * nz, 0.0, 1.0)
        shade = base * (0.40 + 0.74 * ndotl)

        # per-material shimmer / twinkle / surface lift
        is_tinsel = mat == TINSEL
        if np.any(is_tinsel):
            tw = 0.74 + 0.36 * np.sin(t * 4.0 + phase[is_tinsel])
            shade[is_tinsel] = (0.34 + 0.72 * ndotl[is_tinsel]) * tw

        is_light = mat == LIGHT
        if np.any(is_light):
            pulse = 0.48 + 0.68 * (0.5 + 0.5 * np.sin(t * 4.2 + phase[is_light]))
            shade[is_light] = pulse

        is_ball = mat == BALL
        if np.any(is_ball):
            spec = np.clip(-0.30 * nx[is_ball] + 0.48 * ny[is_ball] + 0.82 * nz[is_ball], 0.0, 1.0) ** 9
            shade[is_ball] = 0.42 + 0.68 * ndotl[is_ball] + 0.55 * spec

        is_box = (mat == BOX) | (mat == RIBBON)
        if np.any(is_box):
            shade[is_box] = 0.52 + 0.62 * ndotl[is_box]

        is_trunk = mat == TRUNK
        if np.any(is_trunk):
            shade[is_trunk] = 0.65 + 0.45 * ndotl[is_trunk]

        # depth cue: the far side of the tree, seen through gaps, sinks into shadow so branch tiers
        # read as layers; emissive lights keep most of their brightness
        front = np.clip(0.5 + 0.55 * rz, 0.0, 1.0)
        shade *= np.where(is_light, 0.75 + 0.25 * front, 0.48 + 0.52 * front)

        # rare needle glints: each needle tip catches the light for a moment now and then
        cand = np.flatnonzero((mat == NEEDLE) & (base > 0.8) & (front > 0.6))
        if len(cand):
            g = np.sin(t * 1.7 + phase[cand] * 7.0) * np.sin(t * 0.9 + phase[cand] * 3.0)
            idx = cand[g > 0.93]
            shade[idx] = 1.25
            pcol = pcol.copy()
            pcol[idx] = (0.85, 1.0, 0.85)

        # crisp white spawn flash over ~0.36s
        flash = (np.clip(1.0 - age / 0.36, 0.0, 1.0) ** 1.5)[:, None]
        rgb = pcol + (1.0 - pcol) * flash
        lum = shade * (1.0 + 0.85 * flash[:, 0]) + 0.28 * flash[:, 0]

        # project to screen and sort back-to-front (painter's order with subtle material priority)
        px_f, py_f, depth = project(rpos, cols, rows, aspect)
        px = np.rint(px_f).astype(np.int32)
        py = np.rint(py_f).astype(np.int32)
        on_scr = (px >= 0) & (px < cols) & (py >= 0) & (py < rows) & (depth > 0.2)

        px, py = px[on_scr], py[on_scr]
        depth_key = depth[on_scr] - bias[on_scr] - 0.02 * np.minimum(lum[on_scr], 1.2)
        mat, lum, rgb, dith = mat[on_scr], lum[on_scr], rgb[on_scr], dith[on_scr]

        # resolve the front-most point of every cell once, then shade only those (~10x fewer points)
        order = np.argsort(-depth_key, kind="quicksort")
        owner = np.full(rows * cols, -1, dtype=np.int64)
        owner[(py * cols + px)[order]] = order
        cells = np.flatnonzero(owner >= 0)
        win = owner[cells]
        mat, lum, rgb, dith = mat[win], lum[win], rgb[win], dith[win]

        glyph = np.empty(len(win), dtype=np.int32)
        for m_id, ramp in enumerate(RAMP_ARRS):
            sel = mat == m_id
            if np.any(sel):
                # a stable +-0.6 step jitter breaks up flat runs of one glyph, like hand-made ASCII art
                li = np.clip((lum[sel] * len(ramp) + 1.2 * dith[sel]).astype(np.int32), 0, len(ramp) - 1)
                glyph[sel] = ramp[li]

        # lift color slightly relative to glyph density so dark branches remain vivid green;
        # emissive materials keep HDR headroom so tone_map can give them white-hot cores
        vis_gain = np.power(np.clip(lum, 0.0, 1.35), 0.6)[:, None]
        # needles keep an ink floor: depth and shadow show through glyph shape more than through darkness
        foliage = ((mat == NEEDLE) | (mat == INNER))[:, None]
        vis_gain = np.where(foliage, 0.32 + 0.72 * vis_gain, vis_gain)
        hdr = np.where(mat == LIGHT, 1.35, 1.0)[:, None]
        char.flat[cells] = glyph
        col.reshape(-1, 3)[cells] = np.clip(rgb * vis_gain * hdr, 0.0, 2.2)
        emis.flat[cells] = EMIS[mat]
        tree.flat[cells] = True

        # close one- and two-cell holes in the silhouette with dim needles in the local hue
        filled = shift_or(tree, 1, 2)
        filled = ~shift_or(~filled, 1, 2) & ~tree
        if np.any(filled):
            w = tree.astype(np.float32)[..., None]
            avg = box_blur(col * w, 2, 1) / np.maximum(box_blur(w, 2, 1), 1e-3)
            fy, fx = np.nonzero(filled)
            fill_ramp = RAMP_ARRS[INNER]
            char[fy, fx] = fill_ramp[(fx * 7 + fy * 13) % 4 + 1]
            col[fy, fx] = avg[fy, fx] * 0.55
            emis[fy, fx] = EMIS[INNER]
            tree |= filled

    # near snowflakes pass in front of the tree
    nm = snow["near"]
    char[sy[nm], sx[nm]] = snow["glyph"][nm]
    col[sy[nm], sx[nm]] = snow["bright"][nm, None] * np.array([0.92, 0.95, 1.0])
    emis[sy[nm], sx[nm]] = 0.0

    # topper star & burst rays
    if t >= T_STAR:
        on = float(smooth((t - T_STAR) / 0.26))
        flash = float(np.clip(1 - (t - T_STAR) / 1.0, 0, 1) ** 2)
        tx, ty, _ = project(np.array([[0, Y1 + 0.13, 0]]), cols, rows, aspect)
        zoom = view_scales(cols, rows, aspect)[2]
        before = char.copy()
        star(char, col, int(round(tx[0])), int(round(ty[0])),
             (2.3 + 2.7 * on) * zoom * (1 + 0.05 * np.sin(t * 4.0)), t, 1.35, aspect, flash=flash)
        emis[char != before] = 1.0

    # background glow: blurred emissive ink stands in for the pygame bloom pass and fills the dark
    # stripes between rows, so the tree reads as one lit mass rather than as speckle
    zoom = view_scales(cols, rows, aspect)[2]
    e = np.minimum(col, 1.6) * emis[..., None]
    rx, ry = max(1, round(2.5 * zoom)), max(1, round(1.0 * zoom))      # a tight halo, not a wash over the sky
    wide = box_blur(box_blur(e, rx, ry), rx, ry)
    wide = wide.mean(axis=-1, keepdims=True) + 1.4 * (wide - wide.mean(axis=-1, keepdims=True))   # keep hue
    body = box_blur(np.minimum(col, 1.0) * tree[..., None], 2, 1)
    # the snow under and around the tree picks up its light
    lit = (char == ground_char) & (ground_char > 0) & ~tree
    col[lit] += 1.3 * min(glow * 2.0, 1.0) * np.maximum(wide[lit], 0.0)
    sky = SKY_TOP + (SKY_HORIZON - SKY_TOP) * np.clip(np.arange(rows) / (rows * 0.53), 0, 1)[:, None] ** 1.5
    bg = sky[:, None, :] + glow * (0.55 * np.maximum(wide, 0.0) + 0.08 * body)

    # typewriter holiday banner near the bottom
    if t > T_MSG:
        # sit below the front gifts: on short terminals rows - 9 cuts through the base of the tree
        gift_row = int(project(np.array([[0.0, GROUND, 1.3]]), cols, rows, aspect)[1][0]) + 2
        row, x0 = min(rows - 3, max(rows - 9, gift_row)), (cols - len(MESSAGE)) // 2
        shown = min(len(MESSAGE), int((t - T_MSG) * 10))
        char[row - 1:row + 2, max(x0 - 3, 0):x0 + shown + 3] = 0    # clear a clean strip
        for i, ch in enumerate(MESSAGE[:shown]):
            if ch != " ":
                tint = (RED, GOLD, GREEN_BOX)[(i // 2 + int(t * 1.5)) % 3]
                put(char, col, row, x0 + i, ch, tint, 0.85 + 0.25 * np.sin(t * 5 + i * 0.4))

    info["letters"] = int((char > 0).sum())
    if hud:
        line = f"rotation {info['rot_deg']:06.2f} deg   lights {info['lights']:3d}   letters {info['letters']:,}"
        for i, ch in enumerate(line):
            put(char, col, rows - 2, 2 + i, ch, (0.42, 0.46, 0.56), 1.0)
        stamp = f"t {t:05.2f}s"
        for i, ch in enumerate(stamp):
            put(char, col, 1, cols - len(stamp) - 2 + i, ch, ACCENT, 1.0)
    info["bg"] = np.clip(bg, 0.0, 0.5)
    return char, tone_map(col), info


ACCENT = (1.0, 0.77, 0.35)
LOOP_SECONDS = 30.0                                   # the whole show, then it grows again from the start

# ---- the terminal ------------------------------------------------------------------
GLYPHS = np.array([chr(32 + i) for i in range(96)])
ESC = "\x1b"
LEAVE = f"{ESC}[0m{ESC}[?2026l{ESC}[?7h{ESC}[?25h{ESC}[?1049l"


def enter_seq(colours, bold=True):
    bg = f"{ESC}[48;2;{SKY_BG[0]};{SKY_BG[1]};{SKY_BG[2]}m" if colours == "truecolor" else f"{ESC}[48;5;233m"
    weight = f"{ESC}[1m" if bold else ""                  # heavier strokes fill the cell, like the reel's font
    return f"{ESC}[?1049h{ESC}[?25l{ESC}[?7l{ESC}[0m{bg}{weight}{ESC}[2J"


def colour_key(ink, colours):
    """Quantise ink to a per-cell integer key: neighbouring cells with the same key share one colour code."""
    q = (np.clip(ink, 0, 1) * 255).astype(np.int32) >> 3 << 3
    if colours == "256":
        six = (q * 5 + 127) // 255
        return 16 + six[..., 0] * 36 + six[..., 1] * 6 + six[..., 2]
    return (q[..., 0] << 16) | (q[..., 1] << 8) | q[..., 2]


def sgr(key, colours):
    if colours == "256":
        return f"{ESC}[38;5;{key}m"
    return f"{ESC}[38;2;{key >> 16};{(key >> 8) & 255};{key & 255}m"


def bg_key(bg):
    """Quantise background colour more coarsely than ink (steps of 6) so smooth glow runs share codes."""
    q = (np.clip(bg, 0, 1) * 255 / 6).round().astype(np.int32) * 6
    q = np.minimum(q, 255)
    return (q[..., 0] << 16) | (q[..., 1] << 8) | q[..., 2]


def to_ansi(chars, ink, prev=None, colours="truecolor", bg=None):
    """Encode a frame as ANSI bytes, repainting only the rows that changed since `prev`.

    Returns (bytes, state); pass the state back in as `prev`. A blank cell never carries a foreground
    code, and a foreground code is only sent where the colour differs from the last visible cell on its
    row. With `bg` (truecolor only) each cell also carries a background colour, sent where it differs
    from the cell to its left; every repainted row starts with one.
    """
    chars = np.where(chars >= 32, chars, 0)
    key = colour_key(ink, colours)
    rows, cols = chars.shape
    shown = chars != 0
    last = np.maximum.accumulate(np.where(shown, np.arange(cols)[None, :], -1), axis=1)
    before = np.concatenate([np.full((rows, 1), -1), last[:, :-1]], axis=1)
    need = shown & ((before < 0) | (np.take_along_axis(key, np.maximum(before, 0), axis=1) != key))
    use_bg = bg is not None and colours == "truecolor"
    bkey = bg_key(bg) if use_bg else np.zeros_like(key)
    need_bg = np.ones_like(shown)
    if use_bg:
        need_bg[:, 1:] = bkey[:, 1:] != bkey[:, :-1]
    if prev is not None and prev[0].shape == chars.shape and len(prev) > 2:
        stale = ((chars != prev[0]) | (shown & (key != prev[1])) | (bkey != prev[2])).any(axis=1)
    else:
        stale = np.ones(rows, bool)
    letters, codes, bcodes = GLYPHS[np.clip(chars - 32, 0, 95)].tolist(), key.tolist(), bkey.tolist()
    out = [f"{ESC}[?2026h"]
    for r in np.flatnonzero(stale).tolist():
        line, need_r, code_r = letters[r], need[r].tolist(), codes[r]
        out.append(f"{ESC}[{r + 1};1H")
        if not use_bg:
            out.extend(sgr(code_r[c], colours) + line[c] if need_r[c] else line[c] for c in range(cols))
            continue
        nb_r, b_r = need_bg[r].tolist(), bcodes[r]
        for c in range(cols):
            f, b = need_r[c], nb_r[c]
            if f and b:
                k, j = code_r[c], b_r[c]
                out.append(f"{ESC}[38;2;{k >> 16};{(k >> 8) & 255};{k & 255};48;2;{j >> 16};{(j >> 8) & 255};{j & 255}m"
                           + line[c])
            elif b:
                j = b_r[c]
                out.append(f"{ESC}[48;2;{j >> 16};{(j >> 8) & 255};{j & 255}m" + line[c])
            elif f:
                out.append(sgr(code_r[c], colours) + line[c])
            else:
                out.append(line[c])
    out.append(f"{ESC}[?2026l")
    return "".join(out).encode(), (chars.copy(), key, bkey)


def cell_aspect(fd, default=2.0):
    """Height over width of one terminal cell, from the pixel size if the terminal reports it."""
    try:
        rows, cols, xpix, ypix = struct.unpack("HHHH", fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8))
        if xpix and ypix and rows and cols:
            return float(np.clip((ypix / rows) / (xpix / cols), 1.4, 3.0))
    except OSError:
        pass
    return default


def scene_for(cols, rows, cell_h_over_w):
    """Build the point cloud with enough points to fill a grid of this size (more cells, more detail)."""
    aspect = 1.0 / cell_h_over_w
    zoom = view_scales(cols, rows, aspect)[2]
    density = float(np.clip(1.8 * zoom * zoom * aspect / ASPECT0, 1.2, 3.5))
    return build(density), aspect


def write_all(fd, data):
    view = memoryview(data)
    while view:
        try:
            view = view[os.write(fd, view):]
        except BlockingIOError:
            select.select([], [fd], [], 0.05)


def run_live(fps=20.0, aspect=None, speed=1.0, colours=None, seconds=None, loop=True, hud=True, glow=GLOW_DEFAULT, bold=True):
    """Play the tree full-screen in this terminal until a key is pressed, the window is closed or time is up."""
    fd_in, fd_out = sys.stdin.fileno(), sys.stdout.fileno()
    if not (os.isatty(fd_in) and os.isatty(fd_out)):
        sys.exit("xmas-tree needs an interactive terminal")
    colours = colours or ("truecolor" if os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit") else "256")
    saved = termios.tcgetattr(fd_in)
    resized = [True]
    done = [False]

    def restore():
        if not done[0]:
            done[0] = True
            write_all(fd_out, LEAVE.encode())
            termios.tcsetattr(fd_in, termios.TCSADRAIN, saved)

    def stop(*_):
        raise SystemExit(0)

    atexit.register(restore)
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGTSTP):
        signal.signal(sig, stop)
    signal.signal(signal.SIGWINCH, lambda *_: resized.__setitem__(0, True))
    tty.setcbreak(fd_in)
    write_all(fd_out, enter_seq(colours, bold).encode())
    prev, clock, started = None, 0.0, time.perf_counter()
    budget = 1.0 / fps
    scene = None
    try:
        while True:
            t_frame = time.perf_counter()
            if resized[0]:
                resized[0] = False
                size = os.get_terminal_size(fd_out)
                cols, rows = size.columns, size.lines
                scene, cell_aspect_wh = scene_for(cols, rows, aspect or cell_aspect(fd_out))
                prev = None
                seq = enter_seq(colours, bold)
                write_all(fd_out, f"{ESC}[0m{seq[seq.index(ESC + '[48'):]}".encode())
            t_show = clock % LOOP_SECONDS if loop else clock
            chars, ink, info = render(scene, t_show, cols, rows, cell_aspect_wh, hud, glow)
            data, prev = to_ansi(chars, ink, prev, colours, info["bg"] if glow > 0 else None)
            write_all(fd_out, data)
            if seconds is not None and time.perf_counter() - started >= seconds:
                break
            wait = budget - (time.perf_counter() - t_frame)
            if select.select([fd_in], [], [], max(wait, 0.0))[0]:
                os.read(fd_in, 1024)
                break
            # a long stall (laptop asleep, window dragged) must not make the tree jump ahead in one go
            clock += min(time.perf_counter() - t_frame, 0.25) * speed
    finally:
        restore()


def main(argv=None, prog=None):
    parser = argparse.ArgumentParser(prog=prog, description="Rotating ASCII Christmas tree for your terminal. Press any key to quit.")
    parser.add_argument("--fps", type=float, default=20.0, help="frames per second (default 20)")
    parser.add_argument("--aspect", type=float, help="cell height / width (default: detected, else 2.0)")
    parser.add_argument("--speed", type=float, default=1.0, help="animation speed (default 1.0)")
    parser.add_argument("--colors", choices=("truecolor", "256"), help="colour depth (default: from $COLORTERM)")
    parser.add_argument("--seconds", type=float, help="quit by itself after this long")
    parser.add_argument("--once", action="store_true", help="play the grow-in once and keep rotating, instead of looping")
    parser.add_argument("--no-hud", action="store_true", help="hide the rotation / lights / letters readout")
    parser.add_argument("--glow", type=float, default=GLOW_DEFAULT, help=f"background-colour glow strength, 0 = off (default {GLOW_DEFAULT})")
    parser.add_argument("--no-glow", action="store_true", help="same as --glow 0")
    parser.add_argument("--thin", action="store_true", help="regular-weight glyphs instead of bold")
    args = parser.parse_args(argv)
    run_live(args.fps, args.aspect, args.speed, args.colors, args.seconds, not args.once, not args.no_hud,
             0.0 if args.no_glow else args.glow, not args.thin)


if __name__ == "__main__":
    main()
