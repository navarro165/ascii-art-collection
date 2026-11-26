"""Run every command in a directory on a pseudo-terminal, with a minimal environment and no source tree.

    python tools/smoke_installed.py ~/.local/bin

Use it on a `uv tool install` bin dir or on the links `install_binary.sh` makes. It checks that each command
starts, draws on the alternate screen, exits 0 and puts the terminal back, and that the menu reaches an art.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from test_pty import assert_clean, run_pty  # noqa: E402


def main(bin_dir):
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin"}
    for command in ("clownfish", "xmas-tree", "xmas-tree-v1"):
        code, out = run_pty([f"{bin_dir}/{command}", "--seconds", "2"], use_ascii_art=False, source_tree=False, env=env, timeout=40)
        assert_clean(code, out)
        print("ok", command)
    code, out = run_pty([f"{bin_dir}/ascii-art", "clown", "--seconds", "1"], use_ascii_art=False, source_tree=False, env=env, timeout=40)
    assert_clean(code, out)
    print("ok ascii-art clown")
    code, out = run_pty([f"{bin_dir}/ascii-art"], steps=[(2.0, b"\x1b[B\r"), (6.0, b"q")], use_ascii_art=False, source_tree=False, env=env, timeout=40)
    assert code == 0 and out.count(b"\x1b[?1049h") >= 2, out[-300:]
    print("ok menu -> xmas-tree -> quit")


if __name__ == "__main__":
    main(str(Path(sys.argv[1]).expanduser().resolve()))
