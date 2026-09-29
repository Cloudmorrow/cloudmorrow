"""The server uninstaller: it lists what it would remove, keeps the data when
asked, and refuses to delete a directory the system needs."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

UNINSTALLER = Path(__file__).resolve().parent.parent / "deploy" / "uninstall-server.sh"
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def dry_run(*args: str) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["sh", str(UNINSTALLER), "--dry-run", *args],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        env=os.environ,
        timeout=60,
    )
    result.stdout = ANSI.sub("", result.stdout)
    result.stderr = ANSI.sub("", result.stderr)
    return result


def made(tmp_path: Path) -> list[str]:
    """What an install with custom paths leaves on disk."""
    dirs = [tmp_path / "opt", tmp_path / "notes", tmp_path / "data"]
    for d in dirs:
        d.mkdir()
    return [
        "--prefix",
        str(dirs[0]),
        "--notes-dir",
        str(dirs[1]),
        "--data-dir",
        str(dirs[2]),
        "--service-user",
        "nobody-here-at-all",
    ]


def test_uninstaller_is_valid_posix_shell():
    subprocess.run(["sh", "-n", str(UNINSTALLER)], check=True)


def test_dry_run_lists_everything_and_removes_nothing(tmp_path):
    result = dry_run(*made(tmp_path))
    assert result.returncode == 0, result.stderr + result.stdout
    for name in ("opt", "notes", "data"):
        assert f"- {tmp_path / name}" in result.stdout
        assert f"would run: rm -rf {tmp_path / name}" in result.stdout
        assert (tmp_path / name).is_dir()
    assert "Every account, note, file and secret on it goes too." in result.stdout
    assert "nothing was removed" in result.stdout


def test_keep_data_takes_only_the_software(tmp_path):
    result = dry_run(*made(tmp_path), "--keep-data")
    assert result.returncode == 0, result.stderr + result.stdout
    assert f"would run: rm -rf {tmp_path / 'opt'}" in result.stdout
    assert f"rm -rf {tmp_path / 'notes'}" not in result.stdout
    assert f"rm -rf {tmp_path / 'data'}" not in result.stdout
    assert "userdel" not in result.stdout


def test_refuses_to_delete_a_system_directory(tmp_path):
    paths = made(tmp_path)
    for bad in ("/", "/var/lib", "/srv/", "relative/notes"):
        result = dry_run(*paths, "--notes-dir", bad)
        assert result.returncode != 0
        assert "rm -rf" not in result.stdout
