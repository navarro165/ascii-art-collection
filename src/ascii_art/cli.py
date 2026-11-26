"""The `ascii-art` command: pick an art from a menu, or name one and pass its flags straight through.

The same entry point also serves the `clownfish`, `xmas-tree` and `xmas-tree-v1` commands: when the
program is invoked under an art's name it runs that art directly, which works for installed scripts
and for symlinks into a frozen bundle alike.
"""
import os
import sys
from typing import NamedTuple

from ascii_art import __version__, selector
from ascii_art.arts import clownfish, xmas_tree, xmas_tree_v1


class Art(NamedTuple):
    module: object
    blurb: str
    credit: str


ARTS = {
    "clownfish": Art(clownfish, "A clownfish swimming round a swaying anemone", "ASCII Lab by Alexandr Sapozhkov"),
    "xmas-tree": Art(xmas_tree, "A rotating Christmas tree, v2: bold glyphs, solid gifts, no glow", "dwcminh.ascii, via jaeyonni/XMasTree"),
    "xmas-tree-v1": Art(xmas_tree_v1, "The first terminal port of the Christmas tree", "dwcminh.ascii, via jaeyonni/XMasTree"),
}

USAGE = """usage: ascii-art [--list | --version | --help]
       ascii-art <art> [art options]     (a unique prefix of the name works)

With no arguments, shows a menu. Each art also has its own command: {names}.
Try `ascii-art <art> --help` for the options of one art."""


def listing():
    width = max(map(len, ARTS))
    return "\n".join(f"  {name:<{width}}  {art.blurb} (credit: {art.credit})" for name, art in ARTS.items())


def resolve(word):
    """Return the art named by `word` (exact, else a unique prefix) or None."""
    if word in ARTS:
        return word
    matches = [name for name in ARTS if name.startswith(word)]
    return matches[0] if len(matches) == 1 else None


def run(name, argv, prog):
    ARTS[name].module.main(argv, prog=prog)
    return 0


def menu():
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("ascii-art needs a terminal for its menu. Name an art instead:\n" + listing(), file=sys.stderr)
        return 2
    choice = selector.choose([(name, art.blurb, art.credit) for name, art in ARTS.items()])
    return 0 if choice is None else run(choice, [], f"ascii-art {choice}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    invoked = os.path.basename(sys.argv[0]).replace("_", "-")
    if invoked in ARTS:
        return run(invoked, argv, invoked)
    if not argv:
        return menu()
    head, rest = argv[0], argv[1:]
    if head in ("-h", "--help"):
        print(USAGE.format(names=", ".join(ARTS)) + "\n\narts:\n" + listing())
        return 0
    if head == "--version":
        print(f"ascii-art {__version__}")
        return 0
    if head == "--list":
        print(listing())
        return 0
    name = resolve(head)
    if name is None:
        close = [n for n in ARTS if n.startswith(head)]
        print(f"ascii-art: {'ambiguous' if close else 'unknown'} art {head!r}" + (f" (could be {', '.join(close)})" if close else ""), file=sys.stderr)
        print(listing(), file=sys.stderr)
        return 2
    return run(name, rest, f"ascii-art {name}")
