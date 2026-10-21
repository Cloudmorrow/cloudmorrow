"""The client starts without the server's packages.

`cloudmorrow[tui,agent]` is what the installer puts on a laptop; the server's
extra, with cryptography, FastAPI and the rest, is not there. A command that
needs some of the server's code imports it when run, and says what is
missing, so that one old venv does not take `cm` down with it (v0.32.0 did).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

SERVER_ONLY = ["cryptography", "fastapi", "pydantic", "jwt", "argon2", "wsgidav", "a2wsgi", "PIL", "uvicorn"]


def without_server_packages(code: str) -> subprocess.CompletedProcess:
    blocked = "".join(f"sys.modules[{name!r}] = None\n" for name in SERVER_ONLY)
    script = "import sys\n" + blocked + textwrap.dedent(code)
    return subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120)


def test_the_cli_and_the_terminal_app_import_without_them():
    done = without_server_packages(
        """
        import cloudmorrow.cli.main
        import cloudmorrow.tui.app
        print("started")
        """
    )
    assert done.returncode == 0, done.stderr
    assert "started" in done.stdout


def test_a_command_that_needs_them_says_so():
    done = without_server_packages(
        """
        from typer.testing import CliRunner
        from cloudmorrow.cli import attest
        result = CliRunner().invoke(attest.app, ["key"])
        print("exit", result.exit_code)
        print(result.output)
        """
    )
    assert done.returncode == 0, done.stderr
    said = " ".join(done.stdout.split())
    assert "exit 1" in said
    assert "needs the cryptography package" in said and "cm update" in said
