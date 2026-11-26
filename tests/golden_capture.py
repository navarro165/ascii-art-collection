"""Capture chars/ink/to_ansi digests from an art module, for the parity baseline in tests/golden/.

The committed digests were captured from the single-file scripts as they were before they moved into the
package (clownfish_term.py as of the first commit; the tree scripts are the earlier standalone versions).

usage: golden.py <clownfish|tree> <file path or dotted module> <out.json>
"""
import hashlib
import importlib
import importlib.util
import json
import sys

import numpy as np

kind, spec, out = sys.argv[1:4]
V1 = kind == "tree-v1"
kind = "tree" if V1 else kind
if spec.endswith(".py"):
    s = importlib.util.spec_from_file_location("art_under_test", spec)
    mod = importlib.util.module_from_spec(s)
    sys.modules["art_under_test"] = mod
    s.loader.exec_module(mod)
else:
    mod = importlib.import_module(spec)

SIZES = [(120, 40), (80, 24)]
TIMES = {"clownfish": [3.0, 11.0], "tree": [0.5, 7.0, 13.0, 28.0]}[kind]
GLOWS = [None] if (V1 or kind == "clownfish") else [0.0, 0.25]


def h(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


res = {}
for cols, rows in SIZES:
    if kind == "clownfish":
        mod.configure(cols, rows, 2.0)
    else:
        scene, asp = mod.scene_for(cols, rows, 2.0)
    for glow in GLOWS:
        for t in TIMES:
            key = f"{cols}x{rows} t={t} glow={glow}"
            if kind == "clownfish":
                chars, ink = mod.grid(t)
                chars2, ink2 = mod.grid(t + 0.05)
                info = info2 = None
            else:
                chars, ink, info = mod.render(scene, t, cols, rows, asp, True, *([] if V1 else [glow]))
                chars2, ink2, info2 = mod.render(scene, t + 0.05, cols, rows, asp, True, *([] if V1 else [glow]))
            for colours in ("truecolor", "256"):
                if kind == "clownfish":
                    data, state = mod.to_ansi(chars, ink, None, colours)
                    data2, _ = mod.to_ansi(chars, ink, state, colours)
                    data3, _ = mod.to_ansi(chars2, ink2, state, colours)
                else:
                    extra = [] if V1 else [info["bg"] if glow > 0 else None]
                    data, state = mod.to_ansi(chars, ink, None, colours, *extra)
                    data2, _ = mod.to_ansi(chars, ink, state, colours, *extra)
                    extra2 = [] if V1 else [info2["bg"] if glow > 0 else None]
                    data3, _ = mod.to_ansi(chars2, ink2, state, colours, *extra2)
                res[f"{key} {colours}"] = {
                    "chars": h(chars), "ink": h(ink),
                    "ansi": hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest(),
                    "ansi_len": len(data),
                    "ansi_delta": hashlib.sha256(data2 if isinstance(data2, bytes) else data2.encode()).hexdigest(),
                    "ansi_next": hashlib.sha256(data3 if isinstance(data3, bytes) else data3.encode()).hexdigest(),
                    "next_len": len(data3),
                }
json.dump(res, open(out, "w"), indent=1, sort_keys=True)
print(len(res), "entries ->", out)
