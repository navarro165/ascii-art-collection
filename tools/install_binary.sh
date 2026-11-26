#!/bin/sh
# Install the bundle built by build_binary.sh: copy it under $PREFIX/<version> and link one command per art
# into $BIN_DIR. Refuses to replace a command that was not linked by a previous run of this script.
set -eu
prefix=${PREFIX:-$HOME/.local/share/ascii-art}
bin_dir=${BIN_DIR:-$HOME/.local/bin}
while [ "${prefix%/}" != "$prefix" ] && [ "$prefix" != "/" ]; do prefix=${prefix%/}; done
while [ "${bin_dir%/}" != "$bin_dir" ] && [ "$bin_dir" != "/" ]; do bin_dir=${bin_dir%/}; done
case $prefix in /*) ;; *) prefix=$PWD/$prefix ;; esac
case $bin_dir in /*) ;; *) bin_dir=$PWD/$bin_dir ;; esac
cd "$(dirname "$0")/.."
bundle=dist/ascii-art
[ -x "$bundle/ascii-art" ] || { echo "no bundle: run tools/build_binary.sh first" >&2; exit 1; }
version=$(sed -n 's/^__version__ = "\([A-Za-z0-9][A-Za-z0-9._+-]\{0,39\}\)".*$/\1/p' src/ascii_art/__init__.py | head -n 1)
[ -n "$version" ] || { echo "cannot read a plain __version__ (letters, digits, . _ + -) from src/ascii_art/__init__.py" >&2; exit 1; }
for cmd in ascii-art clownfish xmas-tree xmas-tree-v1; do
    link=$bin_dir/$cmd
    if [ -e "$link" ] || [ -L "$link" ]; then
        case $(readlink "$link" 2>/dev/null || true) in
            "$prefix"/*) ;;
            *) echo "refusing to replace $link (not linked by this installer under $prefix); remove it first" >&2; exit 1 ;;
        esac
    fi
done
mkdir -p "$prefix" "$bin_dir"
# Copy beside the target first so a failed copy leaves the previous install of this version intact.
rm -rf "$prefix/.incoming"
cp -R "$bundle" "$prefix/.incoming"
rm -rf "${prefix:?}/$version"
mv "$prefix/.incoming" "$prefix/$version"
for cmd in ascii-art clownfish xmas-tree xmas-tree-v1; do
    ln -sfn "$prefix/$version/ascii-art" "$bin_dir/$cmd"
done
echo "installed $version to $prefix/$version; commands linked in $bin_dir"
