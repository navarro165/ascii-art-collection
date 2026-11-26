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
MIN_COLS, MIN_ROWS = 40, 14
KEYS = {b"\x1b[A": "up", b"\x1bOA": "up", b"\x1b[B": "down", b"\x1bOB": "down"}


def write_all(fd, text):
    view = memoryview(text.encode())
    while view:
        try:
            view = view[os.write(fd, view):]
        except BlockingIOError:
            select.select([], [fd], [], 0.05)


def sequence_length(data, i):
    """Length of the escape sequence starting at data[i], or 0 if it is cut off before its final byte."""
    if i + 1 >= len(data):
        return 0
    if data[i + 1:i + 2] == b"[":
        j = i + 2
        while j < len(data) and 0x20 <= data[j] <= 0x3F:
            j += 1
        return j + 1 - i if j < len(data) else 0
    if data[i + 1:i + 2] == b"O":
        return 3 if i + 2 < len(data) else 0
    return 2


def tokens(data):
    """Split raw input into key names: arrows, Enter, single characters; a lone Esc is 'esc'.

    Any other escape sequence (Home, Delete, function keys, Alt+key, mouse reports) is one 'other' token, so
    its parameter bytes are never mistaken for keys.
    """
    i = 0
    while i < len(data):
        for seq, key in KEYS.items():
            if data.startswith(seq, i):
                yield key
                i += len(seq)
                break
        else:
            byte = data[i:i + 1]
            if byte == b"\x1b":
                if i + 1 >= len(data):
                    yield "esc"
                    i += 1
                else:
                    yield "other"
                    i += sequence_length(data, i) or len(data) - i
            elif byte in (b"\r", b"\n"):
                yield "enter"
                i += 1
            else:
                yield byte.decode("latin-1")
                i += 1


def cut_off(data):
    """True if the input ends in the middle of an escape sequence."""
    i = data.rfind(b"\x1b")
    return i >= 0 and (i + 1 == len(data) or sequence_length(data, i) == 0)


def read_keys(fd):
    """Read pending input, waiting briefly for the rest of an escape sequence that was split across reads."""
    data = os.read(fd, 1024)
    while cut_off(data):
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
        lines.append(f" {ESC}[7m{row:<{min(cols, 30)}}{ESC}[0m" if i == index else row)
    lines += ["", clip(blurb, cols - 2), clip(f"credit: {credit}", cols - 2), "", f"run directly: ascii-art {name}", "",
              clip(f"up/down or j/k move, Enter run, 1-{len(entries)} pick, q quit", cols - 2)]
    return f"{ESC}[2J{ESC}[H" + "\r\n".join(line if line.startswith((ESC, " ")) else " " + line for line in lines[: rows - 1])


def choose(entries):
    """Show the menu on the controlling terminal; return the chosen entry's name, or None if the user quit."""
    fd_in, fd_out = sys.stdin.fileno(), sys.stdout.fileno()
    saved = termios.tcgetattr(fd_in)
    dirty = [True]

    def stop(signum, _frame):
        raise SystemExit(128 + signum)

    handlers = {signal.SIGWINCH: lambda *_: dirty.__setitem__(0, True)}
    handlers.update({sig: stop for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT, signal.SIGTSTP)})
    old_handlers = {sig: signal.getsignal(sig) for sig in (*handlers, signal.SIGINT)}
    for sig, handler in handlers.items():
        signal.signal(sig, handler)
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
        # Restoring the terminal must not be interrupted half way by a second signal or Ctrl-C.
        for sig in old_handlers:
            signal.signal(sig, signal.SIG_IGN)
        write_all(fd_out, LEAVE)
        termios.tcsetattr(fd_in, termios.TCSADRAIN, saved)
        for sig, old in old_handlers.items():
            signal.signal(sig, old)
