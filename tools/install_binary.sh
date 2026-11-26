#!/bin/sh
# Install the bundle built by build_binary.sh: copy it under $PREFIX/<version> and link one command per art
# into $BIN_DIR. Refuses to replace a command that was not linked by a previous run of this script.
set -eu
cd "$(dirname "$0")/.."
bundle=dist/ascii-art
[ -x "$bundle/ascii-art" ] || { echo "no bundle: run tools/build_binary.sh first" >&2; exit 1; }
version=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' src/ascii_art/__init__.py)
prefix=${PREFIX:-$HOME/.local/share/ascii-art}
bin_dir=${BIN_DIR:-$HOME/.local/bin}
mkdir -p "$prefix" "$bin_dir"
for cmd in ascii-art clownfish xmas-tree xmas-tree-v1; do
    link=$bin_dir/$cmd
    if [ -e "$link" ] || [ -L "$link" ]; then
        case $(readlink "$link" 2>/dev/null || true) in
            "$prefix"/*) ;;
            *) echo "refusing to replace $link (not from this installer); remove it first" >&2; exit 1 ;;
        esac
    fi
done
rm -rf "$prefix/$version"
cp -R "$bundle" "$prefix/$version"
for cmd in ascii-art clownfish xmas-tree xmas-tree-v1; do
    ln -sf "$prefix/$version/ascii-art" "$bin_dir/$cmd"
done
echo "installed $version to $prefix/$version; commands linked in $bin_dir"
