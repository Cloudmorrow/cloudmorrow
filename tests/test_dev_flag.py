"""`--dev`: the flag that runs the checkout you are standing in.

The hand-over itself is an `execve`, which a test cannot follow — so what these
check is everything that decides it: which directory counts as a checkout, what
would be executed and with what environment, and that the process which has
already been handed over parses its arguments instead of handing over again.
"""

from __future__ import annotations

import os
import sys

import pytest

from cloudmorrow.cli import dev


def checkout(root):
    """A directory shaped enough like the repo to be recognised as one."""
    marker = root / dev.MARKER
    marker.parent.mkdir(parents=True)
    marker.write_text("")
    return root


def test_a_checkout_is_found_from_anywhere_inside_it(tmp_path):
    root = checkout(tmp_path / "cloudmorrow")
    deep = root / "src" / "cloudmorrow" / "tui"
    deep.mkdir(parents=True, exist_ok=True)

    assert dev.find_checkout(root) == root
    assert dev.find_checkout(deep) == root


def test_somewhere_else_is_not_a_checkout(tmp_path):
    assert dev.find_checkout(tmp_path) is None


def test_the_flag_needs_a_checkout_to_point_at(tmp_path, monkeypatch):
    monkeypatch.delenv(dev.ENV, raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exit:
        dev.handle(["--dev", "note", "list"])

    assert "not inside one" in str(exit.value)


def test_it_hands_over_to_the_checkout_venv_when_there_is_one(tmp_path):
    root = checkout(tmp_path / "cloudmorrow")
    venv = root / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("")

    python, arguments, env = dev.command(root, ["note", "list"])

    assert python == str(venv / "python")
    assert arguments == [python, "-m", "cloudmorrow.cli.main", "note", "list"]
    # The working tree ahead of whatever is installed, and a marker saying so.
    assert env["PYTHONPATH"].split(os.pathsep)[0] == str(root / "src")
    assert env[dev.ENV] == str(root)


def test_without_a_venv_it_uses_the_interpreter_it_has(tmp_path):
    root = checkout(tmp_path / "cloudmorrow")

    python, arguments, _ = dev.command(root, [])

    assert python == sys.executable
    assert arguments == [python, "-m", "cloudmorrow.cli.main"]


def test_an_existing_pythonpath_is_kept_behind_the_source(tmp_path, monkeypatch):
    root = checkout(tmp_path / "cloudmorrow")
    monkeypatch.setenv("PYTHONPATH", "/somewhere/else")

    _, _, env = dev.command(root, [])

    assert env["PYTHONPATH"] == os.pathsep.join([str(root / "src"), "/somewhere/else"])


def test_the_handed_over_process_parses_rather_than_handing_over_again(monkeypatch):
    # The tests are the checkout's own code, so this is the handed-over process.
    monkeypatch.setenv(dev.ENV, str(dev.find_checkout()))
    # Would raise rather than exec: nothing here should reach execve.
    monkeypatch.setattr(dev.os, "execve", lambda *a: pytest.fail("handed over twice"))

    assert dev.handle(["--dev", "note", "list"]) == ["note", "list"]


def test_a_stale_marker_does_not_stop_the_hand_over(tmp_path, monkeypatch):
    """`CLOUDMORROW_DEV` left in a shell must not make the installed client pose as the checkout."""
    root = checkout(tmp_path / "cloudmorrow")
    monkeypatch.chdir(root)
    monkeypatch.setenv(dev.ENV, str(root))
    handed = []
    monkeypatch.setattr(dev.os, "execve", lambda python, args, env: handed.append((args, env)))

    # The code running is this repo's, not tmp_path's: the marker lies.
    assert dev.checkout() is None
    dev.handle(["--dev", "version"])

    assert handed, "should have handed over to the checkout"
    args, env = handed[0]
    assert args[1:] == ["-m", "cloudmorrow.cli.main", "version"]
    assert env[dev.ENV] == str(root)


def test_without_the_flag_nothing_happens_at_all(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(dev.ENV, raising=False)

    assert dev.handle(["note", "list"]) == ["note", "list"]


def test_running_from_source_only_sets_the_label(monkeypatch):
    """The repo's own tests are the checkout's code, so this is that case."""
    monkeypatch.delenv(dev.ENV, raising=False)
    root = dev.find_checkout()
    assert root is not None and dev.running_from(root)
    monkeypatch.setattr(dev.os, "execve", lambda *a: pytest.fail("no need to hand over"))

    assert dev.handle(["--dev"]) == []
    assert dev.checkout() == root
