"""Frames from the packaged arts must match, bit for bit, the digests captured from the original files."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from ascii_art.arts import clownfish, xmas_tree, xmas_tree_v1

GOLDEN = Path(__file__).parent / "golden"
SIZES = [(120, 40), (80, 24)]


def digest(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def frames(kind):
    """Yield (key, chars, ink, ansi digests) in the same order and with the same parameters as the capture."""
    for cols, rows in SIZES:
        if kind == "clownfish":
            clownfish.configure(cols, rows, 2.0)
        else:
            mod = xmas_tree if kind == "xmas_tree" else xmas_tree_v1
            scene, asp = mod.scene_for(cols, rows, 2.0)
        glows = [0.0, 0.25] if kind == "xmas_tree" else [None]
        times = [3.0, 11.0] if kind == "clownfish" else [0.5, 7.0, 13.0, 28.0]
        for glow in glows:
            for t in times:
                if kind == "clownfish":
                    chars, ink = clownfish.grid(t)
                    info, extra = None, []
                elif kind == "xmas_tree":
                    chars, ink, info = xmas_tree.render(scene, t, cols, rows, asp, True, glow)
                    extra = [info["bg"] if glow > 0 else None]
                else:
                    chars, ink, info = xmas_tree_v1.render(scene, t, cols, rows, asp, True)
                    extra = []
                to_ansi = {"clownfish": clownfish, "xmas_tree": xmas_tree, "xmas_tree_v1": xmas_tree_v1}[kind].to_ansi
                for colours in ("truecolor", "256"):
                    data, state = to_ansi(chars, ink, None, colours, *extra)
                    data2, _ = to_ansi(chars, ink, state, colours, *extra)
                    yield f"{cols}x{rows} t={t} glow={glow} {colours}", chars, ink, data, data2


@pytest.mark.parametrize("kind", ["clownfish", "xmas_tree", "xmas_tree_v1"])
def test_frames_match_original(kind):
    golden = json.loads((GOLDEN / f"{kind}.json").read_text())
    seen = 0
    for key, chars, ink, data, data2 in frames(kind):
        want = golden[key]
        assert digest(chars) == want["chars"], key
        assert digest(ink) == want["ink"], key
        assert sha(data) == want["ansi"], key
        assert len(data) == want["ansi_len"], key
        assert sha(data2) == want["ansi_delta"], key
        seen += 1
    assert seen == len(golden)
