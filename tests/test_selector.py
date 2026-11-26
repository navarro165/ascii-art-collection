"""Unit tests for the menu's key parsing, input reading and layout, without a terminal."""
import os
import re
import threading
import time

import pytest

from ascii_art import selector

ENTRIES = [("clownfish", "a fish", "someone"), ("xmas-tree", "a tree", "someone"), ("xmas-tree-v1", "an old tree", "someone")]


@pytest.mark.parametrize("data,expected", [
    (b"j", ["j"]), (b"\r", ["enter"]), (b"\x1b", ["esc"]),
    (b"\x1b[A", ["up"]), (b"\x1bOB", ["down"]), (b"\x1b[B\x1b[A", ["down", "up"]),
    (b"\x1b[3~", ["other"]), (b"\x1b[1;5B", ["other"]), (b"\x1b[<0;5;5M", ["other"]), (b"\x1bOP", ["other"]),
    (b"\x1bj", ["other"]), (b"\x1b2", ["other"]), (b"\x1b[200~12\x1b[201~", ["other", "1", "2", "other"]),
    (b"\x1b[1 q", ["other"]), (b"\x1b[", ["other"]), (b"\x1b[1;", ["other"]), (b"\x1bO", ["other"]),
    (b"j\x1b[3~k", ["j", "other", "k"]), ("²".encode(), ["Â", "²"]),
])
def test_tokens(data, expected):
    assert list(selector.tokens(data)) == expected


@pytest.mark.parametrize("data,cut", [
    (b"", False), (b"j", False), (b"\x1b", True), (b"\x1b[", True), (b"\x1b[1;", True), (b"\x1bO", True),
    (b"\x1b[A", False), (b"\x1bOA", False), (b"\x1b[1;5B", False), (b"\x1bj", False), (b"\x1b[A\x1b", True), (b"j\x1b[3", True),
])
def test_cut_off(data, cut):
    assert selector.cut_off(data) is cut


def feed(first, second, gap):
    read_fd, write_fd = os.pipe()
    os.write(write_fd, first)

    def later():
        time.sleep(gap)
        os.write(write_fd, second)

    thread = threading.Thread(target=later)
    thread.start()
    try:
        return selector.read_keys(read_fd)
    finally:
        thread.join()
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.parametrize("first,second", [(b"\x1b", b"[B"), (b"\x1b[", b"B"), (b"\x1bO", b"B"), (b"\x1b[1", b";5B"), (b"jj\x1b[1;", b"5B")])
def test_read_keys_joins_a_sequence_split_across_reads(first, second):
    assert feed(first, second, 0.01) == first + second


def test_read_keys_gives_up_on_a_sequence_that_never_finishes():
    assert feed(b"\x1b", b"[B", 0.3) == b"\x1b"


def test_read_keys_returns_at_eof_instead_of_spinning():
    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"\x1b")
    os.close(write_fd)
    started = time.monotonic()
    assert selector.read_keys(read_fd) == b"\x1b"
    assert time.monotonic() - started < 1.0
    assert selector.read_keys(read_fd) == b""
    os.close(read_fd)


@pytest.mark.parametrize("index", [0, 1, 2])
def test_frame_rows_stay_aligned_when_the_selection_moves(index):
    frame = selector.frame(ENTRIES, index, 120, 40)
    text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", frame).split("\r\n")
    rows = [line for line in text if re.match(r"\s+\d  ", line)]
    assert [line.index(str(i + 1)) for i, line in enumerate(rows)] == [3, 3, 3]
    assert [line.index(name) for line, (name, _, _) in zip(rows, ENTRIES)] == [6, 6, 6]


def test_frame_says_so_when_the_terminal_is_too_small():
    assert "too small" in selector.frame(ENTRIES, 0, 30, 8)
    assert "too small" not in selector.frame(ENTRIES, 0, selector.MIN_COLS, selector.MIN_ROWS)
