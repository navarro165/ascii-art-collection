"""A small full-screen menu using only the standard library.

`choose` returns the picked name (or None) after putting the terminal back exactly as it found it,
so the caller can start an art, which sets up its own screen, from a clean state.
"""
import os
import select
import signal
import sys
import termios
import tty

ESC = "\x1b"
ENTER = f"{ESC}[?1049h{ESC}[?25l"
LEAVE = f"{ESC}[0m{ESC}[?25h{ESC}[?1049l"
MIN_COLS, MIN_ROWS = 40, 10
KEYS = {b"\x1b[A": "up", b"\x1bOA": "up", b"\x1b[B": "down", b"\x1bOB": "down"}


def write_all(fd, text):
    view = memoryview(text.encode())
    while view:
        try:
            view = view[os.write(fd, view):]
        except BlockingIOError:
            select.select([], [fd], [], 0.05)


def tokens(data):
    """Split raw input into key names: arrows, Enter, single characters; a lone Esc is 'esc'."""
    i = 0
    while i < len(data):
        for seq, key in KEYS.items():
            if data.startswith(seq, i):
                yield key
                i += len(seq)
                break
        else:
            byte = data[i:i + 1]
            i += 1
            if byte == b"\x1b":
                yield "esc" if i >= len(data) else "other"
            elif byte in (b"\r", b"\n"):
                yield "enter"
            else:
                yield byte.decode("latin-1")


def read_keys(fd):
    """Read pending input, waiting briefly for the rest of an escape sequence that was split across reads."""
    data = os.read(fd, 1024)
    while data[-1:] == b"\x1b" or data[-2:] in (b"\x1b[", b"\x1bO"):
        if not select.select([fd], [], [], 0.05)[0]:
            break
        data += os.read(fd, 1024)
    return data


def clip(text, width):
    return text if len(text) <= width else text[: max(width - 1, 0)] + "…"


def frame(entries, index, cols, rows):
    """Return the full-screen text for the menu, with `index` highlighted."""
    if cols < MIN_COLS or rows < MIN_ROWS:
        msg = clip(f"Terminal too small (need {MIN_COLS}x{MIN_ROWS})", cols)
        return f"{ESC}[2J{ESC}[{rows // 2 + 1};{max((cols - len(msg)) // 2, 0) + 1}H{msg}"
    name, blurb, credit = entries[index]
    lines = [f"{ESC}[1mASCII ART COLLECTION{ESC}[0m", ""]
    for i, (n, _, _) in enumerate(entries):
        row = f"  {i + 1}  {n}  "
        lines.append(f"{ESC}[7m{row:<{min(cols, 30)}}{ESC}[0m" if i == index else row)
    lines += ["", clip(blurb, cols - 2), clip(f"credit: {credit}", cols - 2), "", f"run directly: ascii-art {name}", "",
              clip(f"up/down or j/k move, Enter run, 1-{len(entries)} pick, q quit", cols - 2)]
    return f"{ESC}[2J{ESC}[H" + "\r\n".join(" " + line if not line.startswith(ESC) else line for line in lines[: rows - 1])


def choose(entries):
    """Show the menu on the controlling terminal; return the chosen entry's name, or None if the user quit."""
    fd_in, fd_out = sys.stdin.fileno(), sys.stdout.fileno()
    saved = termios.tcgetattr(fd_in)
    dirty = [True]

    def stop(signum, _frame):
        raise SystemExit(128 + signum)

    handlers = {signal.SIGWINCH: lambda *_: dirty.__setitem__(0, True)}
    handlers.update({sig: stop for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT, signal.SIGTSTP)})
    old_handlers = {sig: signal.signal(sig, handler) for sig, handler in handlers.items()}
    index = 0
    try:
        tty.setcbreak(fd_in)
        write_all(fd_out, ENTER)
        while True:
            if dirty[0]:
                dirty[0] = False
                size = os.get_terminal_size(fd_out)
                write_all(fd_out, frame(entries, index, size.columns, size.lines))
            if not select.select([fd_in], [], [], 0.2)[0]:
                continue
            data = read_keys(fd_in)
            if not data:
                return None
            for key in tokens(data):
                if key in ("q", "esc", "\x03"):
                    return None
                if key in ("up", "k"):
                    index, dirty[0] = (index - 1) % len(entries), True
                elif key in ("down", "j"):
                    index, dirty[0] = (index + 1) % len(entries), True
                elif key == "enter":
                    return entries[index][0]
                elif key in "123456789"[: len(entries)]:
                    return entries[int(key) - 1][0]
    except KeyboardInterrupt:
        return None
    finally:
        write_all(fd_out, LEAVE)
        termios.tcsetattr(fd_in, termios.TCSADRAIN, saved)
        for sig, old in old_handlers.items():
            signal.signal(sig, old)
