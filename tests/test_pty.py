"""Run the command under a real pseudo-terminal: arts start and stop cleanly, the menu behaves, the screen is restored."""
import fcntl
import os
import select
import signal
import struct
import subprocess
import sys
import termios
import time
from pathlib import Path

import pytest

SRC = str(Path(__file__).parent.parent / "src")
ALT_ON, ALT_OFF, CURSOR_ON = b"\x1b[?1049h", b"\x1b[?1049l", b"\x1b[?25h"

STUB_DRIVER = """
import sys
from ascii_art import cli

class Stub:
    def __init__(self, name):
        self.name = name
    def main(self, argv, prog=None):
        print("RAN", self.name, argv, prog, flush=True)

cli.ARTS = {k: cli.Art(Stub(k), v.blurb, v.credit) for k, v in cli.ARTS.items()}
%s
sys.exit(cli.main(%s))
"""


def child_setup():
    """Give the child the pty as its controlling terminal and default Ctrl-C handling (a background job inherits SIGINT ignored)."""
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    signal.signal(signal.SIGINT, signal.SIG_DFL)


def set_size(fd, rows, cols):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def run_pty(args, steps=(), size=(40, 120), env=None, timeout=30.0, use_ascii_art=True, source_tree=True):
    """Run `python -m ascii_art args` (or a raw python command) on a pty and return (exit code, output).

    `steps` is a list of (delay_seconds, action) with action one of: bytes to type, ("resize", rows, cols),
    ("signal", signum), ("split", first, second, gap_seconds). Delays count from the moment the program
    enters the alternate screen (after its own terminal setup), so a cold start cannot swallow the keys.
    The pty's termios settings must be the same after the program ends as before it started.
    """
    master, slave = os.openpty()
    set_size(master, *size)
    termios_before = termios.tcgetattr(master)
    full_env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "COLORTERM": "truecolor", "TERM": "xterm-256color"}
    if source_tree:
        full_env["PYTHONPATH"] = SRC
    full_env.update(env or {})
    cmd = [sys.executable, "-m", "ascii_art", *args] if use_ascii_art else list(args)
    proc = subprocess.Popen(cmd, stdin=slave, stdout=slave, stderr=slave, env=full_env, start_new_session=True,
                            preexec_fn=child_setup)
    os.close(slave)
    out, spawned, start = b"", time.monotonic(), None
    pending = sorted(steps, key=lambda s: s[0])
    while True:
        if start is None and ALT_ON in out:
            start = time.monotonic()
        now = 0.0 if start is None else time.monotonic() - start
        while pending and pending[0][0] <= now:
            _, action = pending.pop(0)
            if isinstance(action, tuple) and action[0] == "split":
                os.write(master, action[1])
                time.sleep(action[3])
                os.write(master, action[2])
            elif isinstance(action, tuple) and action[0] == "signal":
                os.killpg(proc.pid, action[1])
            elif isinstance(action, tuple):
                set_size(master, action[1], action[2])
                os.killpg(proc.pid, signal.SIGWINCH)
            else:
                os.write(master, action)
        if select.select([master], [], [], 0.05)[0]:
            try:
                chunk = os.read(master, 65536)
            except OSError:
                chunk = b""
            if not chunk:
                break
            out += chunk
        if proc.poll() is not None and not select.select([master], [], [], 0.1)[0]:
            break
        if time.monotonic() - spawned > timeout:
            proc.kill()
            os.close(master)
            pytest.fail(f"timed out; output tail: {out[-300:]!r}")
    code = proc.wait()
    termios_after = termios.tcgetattr(master)
    os.close(master)
    assert termios_after == termios_before, "terminal settings were not restored"
    return code, out


def assert_clean(code, out):
    assert code == 0, out[-500:]
    assert b"Traceback" not in out
    assert ALT_ON in out and ALT_OFF in out and CURSOR_ON in out


@pytest.mark.parametrize("art", ["clownfish", "xmas-tree", "xmas-tree-v1"])
def test_art_runs_and_restores_terminal(art):
    assert_clean(*run_pty([art, "--seconds", "2"]))


@pytest.mark.parametrize("art", ["clownfish", "xmas-tree", "xmas-tree-v1"])
def test_key_press_quits_quickly(art):
    started = time.monotonic()
    code, out = run_pty([art], steps=[(1.5, b"q")])
    assert_clean(code, out)
    assert time.monotonic() - started < 4.0


@pytest.mark.parametrize("art", ["clownfish", "xmas-tree", "xmas-tree-v1"])
def test_ctrl_c_quits_quietly_and_restores_terminal(art):
    code, out = run_pty([art], steps=[(1.5, b"\x03")])
    assert code == 130
    assert b"Traceback" not in out and ALT_OFF in out and CURSOR_ON in out


@pytest.mark.parametrize("art", ["clownfish", "xmas-tree", "xmas-tree-v1"])
def test_256_colour_mode_uses_no_truecolor(art):
    code, out = run_pty([art, "--colors", "256", "--seconds", "1"])
    assert_clean(code, out)
    assert b"38;5;" in out and b"38;2;" not in out


@pytest.mark.parametrize("art", ["clownfish", "xmas-tree", "xmas-tree-v1"])
def test_resize_redraws_without_error(art):
    code, out = run_pty([art, "--seconds", "3"], steps=[(1.0, ("resize", 24, 80))])
    assert_clean(code, out)
    assert out.count(b"\x1b[2J") >= 2


@pytest.mark.parametrize("art", ["clownfish", "xmas-tree", "xmas-tree-v1"])
@pytest.mark.parametrize("size", [(6, 20), (90, 300)])
def test_extreme_sizes_do_not_crash(art, size):
    assert_clean(*run_pty([art, "--seconds", "2"], size=size))


def test_tree_accepts_all_its_flags():
    assert_clean(*run_pty(["xmas-tree", "--once", "--no-hud", "--thin", "--glow", "0.5", "--seconds", "2"]))


def test_unique_prefix_runs_the_art():
    assert_clean(*run_pty(["clown", "--seconds", "1"]))


def test_direct_command_name_dispatch(tmp_path):
    link = tmp_path / "clownfish"
    link.symlink_to(Path(SRC).parent / "tests" / "_entry.py")
    code, out = run_pty([sys.executable, str(link), "--seconds", "1"], use_ascii_art=False)
    assert_clean(code, out)


def test_no_tty_and_unknown_name_exit_2():
    base = [sys.executable, "-m", "ascii_art"]
    env = {**os.environ, "PYTHONPATH": SRC}
    assert subprocess.run(base, stdin=subprocess.DEVNULL, capture_output=True, env=env).returncode == 2
    assert subprocess.run([*base, "nope"], capture_output=True, env=env).returncode == 2
    assert subprocess.run([*base, "--version"], capture_output=True, env=env).returncode == 0


def menu(steps, size=(40, 120), setup=""):
    return run_pty([sys.executable, "-c", STUB_DRIVER % (setup, "[]")], steps=steps, size=size, use_ascii_art=False)


def test_menu_lists_all_arts():
    code, out = menu([(0.8, b"q")])
    assert code == 0
    for name in (b"clownfish", b"xmas-tree", b"xmas-tree-v1"):
        assert name in out


@pytest.mark.parametrize("keys,expected", [(b"\r", b"RAN clownfish"), (b"\x1b[B\r", b"RAN xmas-tree "), (b"jj\r", b"RAN xmas-tree-v1"),
                                           (b"3", b"RAN xmas-tree-v1"), (b"\x1bOB\r", b"RAN xmas-tree "), (b"\x1b[A\r", b"RAN xmas-tree-v1")])
def test_menu_selection_launches_art(keys, expected):
    code, out = menu([(0.8, keys)])
    assert code == 0
    assert expected in out
    assert out.index(ALT_OFF) < out.index(b"RAN")


@pytest.mark.parametrize("key", ["²".encode(), "ó".encode(), b"0", b"9", b"\x00", b"\xff"])
def test_menu_ignores_stray_keys(key):
    code, out = menu([(0.8, key), (1.4, b"q")])
    assert code == 0 and b"Traceback" not in out and b"RAN" not in out


@pytest.mark.parametrize("key", [b"q", b"\x1b", b"\x03"])
def test_menu_quit_keys_restore_terminal(key):
    code, out = menu([(0.8, key)])
    assert code == 0
    assert b"RAN" not in out
    assert out.rstrip().endswith(ALT_OFF) and CURSOR_ON in out


@pytest.mark.parametrize("action", [("signal", signal.SIGTERM), ("signal", signal.SIGHUP), b"\x1c", b"\x1a"])
def test_menu_restores_terminal_on_fatal_signals(action):
    code, out = menu([(0.8, action)])
    assert code != 0 and b"RAN" not in out
    assert out.rstrip().endswith(ALT_OFF) and CURSOR_ON in out


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGHUP, signal.SIGINT])
def test_signal_right_after_quit_still_restores_the_terminal(sig):
    """The signal lands in the same tick as `q`, i.e. while the menu is leaving; run_pty checks termios afterwards."""
    code, out = menu([(0.5, b"q"), (0.5, ("signal", sig))])
    assert out.rstrip().endswith(ALT_OFF) and b"Traceback" not in out


@pytest.mark.parametrize("keys", [b"\x1b[3~", b"\x1b[1~", b"\x1b[1;5B", b"\x1b[15~", b"\x1bj", b"\x1b[<0;5;5M", b"\x1bOP", b"\x1b2", b"\x1b[200~12\x1b[201~"])
def test_menu_treats_other_escape_sequences_as_ignored_keys(keys):
    """Enter afterwards must still run the FIRST art: nothing in the sequence moved the selection or picked an art."""
    code, out = menu([(0.5, keys), (1.0, b"\r")])
    assert code == 0 and b"RAN clownfish" in out


@pytest.mark.parametrize("first,second,expected", [(b"\x1b[", b"B\r", b"RAN xmas-tree "), (b"\x1bO", b"B\r", b"RAN xmas-tree "),
                                                   (b"\x1b[1;", b"5B\r", b"RAN clownfish"), (b"\x1b", b"[B\r", b"RAN xmas-tree ")])
def test_menu_sequence_split_across_reads(first, second, expected):
    code, out = menu([(0.5, ("split", first, second, 0.02))])
    assert code == 0 and expected in out


def test_menu_survives_closed_stdin():
    code = subprocess.run(f"{sys.executable} -m ascii_art <&-", shell=True, env={**os.environ, "PYTHONPATH": SRC}, capture_output=True).returncode
    assert code == 2


def test_menu_redraws_on_resize_and_handles_tiny_terminal():
    code, out = menu([(0.6, ("resize", 6, 30)), (1.2, ("resize", 40, 120)), (1.8, b"q")])
    assert code == 0
    assert b"Terminal too small" in out
    assert out.count(b"ASCII ART COLLECTION") >= 2


def test_menu_crash_still_restores_terminal():
    code, out = menu([], setup="from ascii_art import selector\ndef boom(*a):\n    raise RuntimeError('boom')\nselector.frame = boom")
    assert code != 0 and b"boom" in out
    assert out.rstrip().endswith(ALT_OFF) or ALT_OFF in out.split(b"Traceback")[0]
