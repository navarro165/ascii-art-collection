"""tools/install_binary.sh against a fake bundle: relative paths, a bad version line, and a failed run leaving things alone."""
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent


def fake_repo(tmp_path, version_line='__version__ = "0.1.0"'):
    repo = tmp_path / "repo"
    (repo / "tools").mkdir(parents=True)
    (repo / "src" / "ascii_art").mkdir(parents=True)
    (repo / "dist" / "ascii-art").mkdir(parents=True)
    shutil.copy(ROOT / "tools" / "install_binary.sh", repo / "tools")
    (repo / "src" / "ascii_art" / "__init__.py").write_text(version_line + "\n")
    exe = repo / "dist" / "ascii-art" / "ascii-art"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return repo


def install(repo, cwd, **env):
    return subprocess.run(["sh", str(repo / "tools" / "install_binary.sh")], cwd=cwd, capture_output=True, text=True, env={**os.environ, **env})


def test_relative_paths_resolve_against_the_callers_directory(tmp_path):
    repo, cwd = fake_repo(tmp_path), tmp_path / "work"
    cwd.mkdir()
    result = install(repo, cwd, PREFIX="share", BIN_DIR="bin")
    assert result.returncode == 0, result.stderr
    link = cwd / "bin" / "clownfish"
    assert link.resolve() == (cwd / "share" / "0.1.0" / "ascii-art").resolve() and link.exists()
    assert not (repo / "share").exists()


def test_unreadable_version_stops_before_touching_the_prefix(tmp_path):
    repo = fake_repo(tmp_path, "__version__ = '0.1.0'")
    prefix = tmp_path / "prefix"
    (prefix / "keepme").mkdir(parents=True)
    (prefix / "keepme" / "f").write_text("x")
    result = install(repo, tmp_path, PREFIX=str(prefix), BIN_DIR=str(tmp_path / "bin"))
    assert result.returncode != 0
    assert (prefix / "keepme" / "f").exists()


def test_refuses_to_replace_a_foreign_command(tmp_path):
    repo, bin_dir = fake_repo(tmp_path), tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "clownfish").symlink_to("/bin/ls")
    result = install(repo, tmp_path, PREFIX=str(tmp_path / "share"), BIN_DIR=str(bin_dir))
    assert result.returncode == 1 and "refusing" in result.stderr
    assert not (tmp_path / "share" / "0.1.0").exists()
