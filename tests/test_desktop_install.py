"""Getting the desktop app onto a computer: install.sh, the launcher, `cm app`.

install.sh is run for real here, against a Python that only writes down
what it was asked to do — so what is checked is what the script would
actually run on a machine with a desktop, on one without, and when told
`--no-desktop`.
"""

from __future__ import annotations

import os
import platform
import stat
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cloudmorrow.cli import uninstall
from cloudmorrow.cli.main import app as cli
from cloudmorrow.client.config import ClientConfig
from cloudmorrow.desktop import launcher
from cloudmorrow.desktop.extra import with_extra

# -- the requirement -------------------------------------------------------------


def test_the_desktop_extra_is_added_to_whatever_the_server_hands_out():
    assert with_extra("cloudmorrow[tui,agent]") == "cloudmorrow[tui,agent,desktop]"
    assert (
        with_extra("cloudmorrow[tui,agent] @ https://c.example/dist/cloudmorrow-1.0-py3-none-any.whl")
        == "cloudmorrow[tui,agent,desktop] @ https://c.example/dist/cloudmorrow-1.0-py3-none-any.whl"
    )
    assert with_extra("cloudmorrow") == "cloudmorrow[desktop]"
    assert with_extra("cloudmorrow[desktop]") == "cloudmorrow[desktop]"


def test_the_script_carries_both_requirements(client):
    script = client.get("/install.sh").text
    assert 'PACKAGE="cloudmorrow[tui,agent]"' in script
    assert 'DESKTOP_PACKAGE="cloudmorrow[tui,agent,desktop]"' in script
    assert "--no-desktop" in script
    assert "app --install-launcher" in script
    # A Mac and Windows are named as not done, rather than half done.
    assert "TODO(macos)" in script and "TODO(windows)" in script


# -- running it --------------------------------------------------------------------

FAKE_PYTHON = """#!/bin/sh
echo "python3 $*" >> "$LOG"
case "$1" in
-c) exit 0 ;;
-V) echo "Python 3.12.0"; exit 0 ;;
-m)
	if [ "$2" = venv ]; then
		mkdir -p "$3/bin"
		cp "$FAKE/venv-python" "$3/bin/python"
		cp "$FAKE/cloudmorrow" "$3/bin/cloudmorrow"
	fi
	exit 0 ;;
esac
"""
LOGGER = """#!/bin/sh
echo "{name} $*" >> "$LOG"
"""


@pytest.fixture()
def run_installer(client, tmp_path):
    if platform.system() != "Linux" or os.geteuid() == 0:
        pytest.skip("the desktop step is for a Linux user, not root")
    script = tmp_path / "install.sh"
    script.write_text(client.get("/install.sh").text)
    fake = tmp_path / "fake"
    fake.mkdir()
    for name, text in {
        "python3.14": FAKE_PYTHON,
        "venv-python": LOGGER.format(name="venv-python"),
        "cloudmorrow": LOGGER.format(name="cloudmorrow"),
    }.items():
        path = fake / name
        path.write_text(text)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "log"

    def run(*args: str, display: bool) -> tuple[str, list[str]]:
        env = {
            "PATH": f"{fake}:/usr/bin:/bin",
            "HOME": str(tmp_path / "home"),
            "LOG": str(log),
            "FAKE": str(fake),
        }
        if display:
            env["WAYLAND_DISPLAY"] = "wayland-1"
        log.write_text("")
        done = subprocess.run(
            ["sh", str(script), *args], env=env, capture_output=True, text=True, timeout=60
        )
        assert done.returncode == 0, done.stderr
        return done.stdout + done.stderr, log.read_text().splitlines()

    return run


def test_a_desktop_gets_the_desktop_app_and_a_launcher(run_installer):
    output, calls = run_installer(display=True)
    assert "venv-python -m pip install --quiet cloudmorrow[tui,agent,desktop]" in calls
    assert "cloudmorrow app --install-launcher" in calls
    assert "cloudmorrow app" in output
    # On top of the usual install, not instead of it.
    assert any("--force-reinstall cloudmorrow[tui,agent]" in call for call in calls)


def test_no_desktop_says_no(run_installer):
    output, calls = run_installer("--no-desktop", display=True)
    assert not any("desktop]" in call for call in calls)
    assert "cloudmorrow app --install-launcher" not in calls
    assert "--no-desktop" in output


def test_a_machine_without_a_display_gets_the_terminal_app_as_before(run_installer):
    output, calls = run_installer(display=False)
    assert not any("desktop]" in call for call in calls)
    assert "cloudmorrow app --install-launcher" not in calls
    assert "cloudmorrow app" not in output


# -- the launcher --------------------------------------------------------------------


@pytest.fixture()
def data_home(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setattr(launcher.system, "os_name", lambda: "linux")
    return tmp_path / "share"


def test_the_launcher_runs_cm_app_with_the_hedgehog(data_home):
    written = launcher.install("The Larsens")
    entry = data_home / "applications" / "cloudmorrow.desktop"
    icon = data_home / "icons" / "hicolor" / "512x512" / "apps" / "cloudmorrow.png"
    assert written == [entry, icon]
    text = entry.read_text()
    assert "Name=The Larsens\n" in text
    assert "Icon=cloudmorrow\n" in text
    assert "Terminal=false\n" in text
    exec_line = next(line for line in text.splitlines() if line.startswith("Exec="))
    assert exec_line.endswith(" app")
    assert icon.read_bytes().startswith(b"\x89PNG")
    # Again is fine: the same two files, written anew.
    assert launcher.install("The Larsens") == written


def test_uninstall_takes_the_launcher_away(data_home):
    launcher.install()
    # Only looked at: the rest of a real plan is this machine's own install.
    assert uninstall.plan().launcher == launcher.installed()
    found = uninstall.Plan(launcher=launcher.installed())
    assert any("desktop app's launcher" in line for line in found.lines())
    uninstall.remove(found)
    assert launcher.installed() == []


def test_a_mac_is_told_there_is_no_launcher_yet(monkeypatch):
    monkeypatch.setattr(launcher.system, "os_name", lambda: "macos")
    with pytest.raises(launcher.LauncherError, match="only made on Linux"):
        launcher.install()


# -- cm app ------------------------------------------------------------------------------


def test_cm_app_prints_the_address_it_would_open():
    ClientConfig(api_url="https://cloud.example").save()
    result = CliRunner().invoke(cli, ["app", "--print-url"])
    assert result.exit_code == 0
    assert result.stdout == "https://cloud.example/app\n"


def test_cm_app_dry_run_says_what_and_whether(monkeypatch):
    from cloudmorrow.desktop import app as desktop_app

    ClientConfig(api_url="https://cloud.example").save()
    monkeypatch.setattr(desktop_app, "cloud_name", lambda config: "The Larsens")
    monkeypatch.setattr(desktop_app.system, "has_display", lambda: False)
    result = CliRunner().invoke(cli, ["app", "--dry-run"])
    assert result.exit_code == 0
    assert "https://cloud.example/app" in result.output
    assert "The Larsens" in result.output
    assert "a window cannot open here" in result.output


def test_cm_app_without_a_display_says_so_and_fails(monkeypatch):
    from cloudmorrow.desktop import app as desktop_app

    ClientConfig(api_url="https://cloud.example").save()
    monkeypatch.setattr(desktop_app.system, "has_display", lambda: False)
    result = CliRunner().invoke(cli, ["app"])
    assert result.exit_code == 1
    assert "no display" in result.output
