"""The committed README images must be what tools/make_images.py produces today."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
pytest.importorskip("PIL")
FONTS = ("/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")


@pytest.mark.skipif(not any(Path(f).exists() for f in FONTS), reason="needs the Menlo or DejaVu Sans Mono font")
def test_committed_images_are_reproducible(tmp_path):
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_images.py"), "--out", str(tmp_path)], check=True, capture_output=True)
    for name in ("clownfish.png", "xmas-tree.png"):
        assert (tmp_path / name).read_bytes() == (ROOT / "docs" / "images" / name).read_bytes(), name
