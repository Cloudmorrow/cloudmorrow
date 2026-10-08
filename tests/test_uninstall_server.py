"""The server uninstaller: it shows what the installer made as boxes to tick,
only the services ticked, removes what is ticked, and refuses to delete a
directory the system needs."""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UNINSTALLER = REPO / "deploy" / "uninstall-server.sh"
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def made(tmp_path: Path, *, checkout: bool = False) -> list[str]:
    """What an install with custom paths leaves on disk: the flags that find it.

    With *checkout*, the code directory has the package in it, the way a
    real install does, so the uninstaller can ask with the tick-box list.
    """
    for name in ("opt", "notes", "data", "etc"):
        (tmp_path / name).mkdir()
    (tmp_path / "etc" / "server.toml").write_text('[server]\nname = "Trial"\n')
    if checkout:
        (tmp_path / "opt" / "src").symlink_to(REPO / "src")
    return [
        "--prefix",
        str(tmp_path / "opt"),
        "--notes-dir",
        str(tmp_path / "notes"),
        "--data-dir",
        str(tmp_path / "data"),
        "--config-dir",
        str(tmp_path / "etc"),
        "--service-user",
        "nobody-here-at-all",
    ]


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


def test_uninstaller_is_valid_posix_shell():
    subprocess.run(["sh", "-n", str(UNINSTALLER)], check=True)


def test_delete_data_lists_everything_and_removes_nothing(tmp_path):
    result = dry_run(*made(tmp_path), "--delete-data")
    assert result.returncode == 0, result.stderr + result.stdout
    for name in ("opt", "notes", "data", "etc"):
        assert f"would run: rm -rf {tmp_path / name}" in result.stdout
        assert (tmp_path / name).is_dir()
    assert "cannot be brought back" in result.stdout
    assert "nothing was removed" in result.stdout


def test_a_dry_run_is_an_inventory_with_only_the_services_ticked(tmp_path):
    result = dry_run(*made(tmp_path))
    assert result.returncode == 0, result.stderr + result.stdout
    assert 'the Cloudmorrow server "Trial"' in result.stdout
    for label in ("Code", "Config", "Data", "Notes"):
        assert f"[ ] {label}" in result.stdout
    assert "[x]" not in result.stdout  # no units on this machine: nothing to tick
    assert "Ticked is what goes" in result.stdout
    assert "rm -rf" not in result.stdout


def test_remove_picks_what_goes(tmp_path):
    result = dry_run(*made(tmp_path), "--remove", "code,notes")
    assert result.returncode == 0, result.stderr + result.stdout
    assert f"would run: rm -rf {tmp_path / 'opt'}" in result.stdout
    assert f"would run: rm -rf {tmp_path / 'notes'}" in result.stdout
    assert f"rm -rf {tmp_path / 'data'}" not in result.stdout
    assert f"rm -rf {tmp_path / 'etc'}" not in result.stdout
    assert "keeps the config, data" in result.stdout
    assert "userdel" not in result.stdout


def test_remove_rejects_a_kind_it_does_not_know(tmp_path):
    result = dry_run(*made(tmp_path), "--remove", "everything")
    assert result.returncode != 0
    assert 'does not know "everything"' in result.stderr
    assert "rm -rf" not in result.stdout


def test_refuses_to_delete_a_system_directory(tmp_path):
    paths = made(tmp_path)
    for bad in ("/", "/var/lib", "/srv/", "."):
        result = dry_run(*paths, "--delete-data", "--notes-dir", bad)
        assert result.returncode != 0
        assert "rm -rf" not in result.stdout


# --- on a terminal ----------------------------------------------------------------
# A real run, as the uninstaller would be used, on a pseudo-terminal that is
# the script's controlling terminal (it asks on /dev/tty). Root is not needed
# to remove directories in tmp_path, so `id -u` is shimmed to say 0; nothing
# else the script calls needs privilege when the units and user are not there.


def root_shim(tmp_path: Path) -> dict[str, str]:
    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "id").write_text('#!/bin/sh\n[ "$1" = "-u" ] && { echo 0; exit 0; }\nexec /usr/bin/id "$@"\n')
    (shim / "id").chmod(0o755)
    return {**os.environ, "PATH": f"{shim}:{os.environ['PATH']}", "NO_COLOR": "1"}


def on_a_terminal(args: list[str], env: dict[str, str], conversation: list[tuple[str, bytes]]) -> tuple[int, str]:
    """Run the uninstaller on a pty; type each reply once its prompt has shown."""
    import fcntl
    import struct
    import termios

    main_fd, side = os.openpty()
    fcntl.ioctl(side, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))
    drawn = bytearray()

    def drain():
        while True:
            try:
                chunk = os.read(main_fd, 4096)
            except OSError:
                return
            if not chunk:
                return
            drawn.extend(chunk)

    def become_the_terminals_session():
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    process = subprocess.Popen(
        ["sh", str(UNINSTALLER), *args],
        stdin=side,
        stdout=side,
        stderr=side,
        env=env,
        start_new_session=True,
        preexec_fn=become_the_terminals_session,
    )
    os.close(side)
    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        for prompt, reply in conversation:
            deadline = time.monotonic() + 20
            while prompt not in ANSI.sub("", drawn.decode("utf-8", "replace")):
                if process.poll() is not None or time.monotonic() > deadline:
                    raise AssertionError(f"never asked {prompt!r}:\n{drawn.decode('utf-8', 'replace')}")
                time.sleep(0.05)
            os.write(main_fd, reply)
        status = process.wait(timeout=20)
    finally:
        if process.poll() is None:
            process.kill()
        reader.join(timeout=2)
        os.close(main_fd)
    return status, ANSI.sub("", drawn.decode("utf-8", "replace"))


def test_on_a_terminal_it_asks_with_tick_boxes_and_removes_what_is_ticked(tmp_path):
    args = made(tmp_path, checkout=True)
    # Rows: code, config, data, notes. Three down from the top is notes.
    status, screen = on_a_terminal(
        args,
        root_shim(tmp_path),
        [
            ("What should go from this machine?", b"\x1b[B\x1b[B\x1b[B \r"),
            ('Type "delete"', b"delete\n"),
        ],
    )
    assert status == 0, screen
    assert "[x] Notes" in screen
    assert not (tmp_path / "notes").exists()
    for kept in ("opt", "data", "etc"):
        assert (tmp_path / kept).is_dir()
    assert "Kept: the code, config, data." in screen


def test_on_a_terminal_without_the_checkout_it_asks_with_numbers(tmp_path):
    args = made(tmp_path)
    status, screen = on_a_terminal(
        args,
        root_shim(tmp_path),
        [
            ("Numbers [", b"1 3\n"),
            ('Type "delete"', b"delete\n"),
        ],
    )
    assert status == 0, screen
    assert "1  [ ] Code" in screen
    assert not (tmp_path / "opt").exists()
    assert not (tmp_path / "data").exists()
    assert (tmp_path / "notes").is_dir()
    assert (tmp_path / "etc").is_dir()


def test_on_a_terminal_nothing_ticked_removes_nothing(tmp_path):
    args = made(tmp_path)
    status, screen = on_a_terminal(args, root_shim(tmp_path), [("Numbers [", b"\n")])
    assert status == 0, screen
    assert "Nothing ticked: nothing was removed." in screen
    for name in ("opt", "notes", "data", "etc"):
        assert (tmp_path / name).is_dir()
