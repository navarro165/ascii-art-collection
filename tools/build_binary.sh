#!/bin/sh
# Build a dependency-free, one-directory bundle into dist/ascii-art/ (no Python or uv needed to run it).
# One-dir rather than one-file on purpose: a one-file build unpacks itself to a temp dir on every launch.
set -eu
cd "$(dirname "$0")/.."
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
# A uv-managed Python is self-contained, so the bundle does not link a Homebrew or system libpython.
uv venv -q --managed-python "$work/venv"
uv pip install -q --python "$work/venv/bin/python" . pyinstaller
rm -rf dist/ascii-art
"$work/venv/bin/pyinstaller" --noconfirm --clean --onedir --name ascii-art \
    --distpath dist --workpath "$work/build" --specpath "$work" \
    --collect-submodules ascii_art tools/_bundle_entry.py
echo "built dist/ascii-art/ascii-art"
