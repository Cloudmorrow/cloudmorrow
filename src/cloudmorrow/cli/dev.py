"""`--dev`: run the checkout you are standing in, not the installed client.

The `cloudmorrow` on your PATH lives in its own venv, and a change to the source
does nothing to it until there is a release and an `update`. That is right for
the client you use and wrong for the one you are working on, so `--dev` says
"the working tree, this once":

    cd ~/Projects/cloudmorrow
    cloudmorrow --dev            # the TUI, from source
    cloudmorrow --dev note list  # any other command, the same way

It is the directory that decides. Standing in a cloudmorrow checkout — anywhere
in it — is what makes the flag mean something; standing anywhere else it has
nothing to point at and says so rather than guessing.

What it does is hand the command over: the checkout's own venv if it has one,
otherwise the interpreter already running, with the source ahead of whatever is
installed. Nothing is copied and nothing is installed, so the next run picks up
whatever the files say at that moment.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

FLAG = "--dev"

# Set on the way in, so the code that takes over knows it is the checkout's own
# — it never hands over a second time, and the TUI can say which one you are
# looking at.
ENV = "CLOUDMORROW_DEV"

# The file that makes a directory this repo rather than any other.
MARKER = Path("src") / "cloudmorrow" / "cli" / "main.py"


def find_checkout(start: Path | None = None) -> Path | None:
    """The cloudmorrow checkout this directory is inside, if it is inside one."""
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        if (directory / MARKER).exists():
            return directory
    return None


def running_from(root: Path) -> bool:
    """True when the code already executing is that checkout's own."""
    import cloudmorrow

    package = Path(cloudmorrow.__file__).resolve().parent
    return package == (root / "src" / "cloudmorrow").resolve()


def interpreter(root: Path) -> str:
    """The checkout's venv if it has one, otherwise the one running us.

    Either can run it — the installed client's venv holds every dependency the
    TUI needs — but a checkout with its own venv is a checkout whose
    dependencies are the ones its pyproject asks for, which is the point of
    standing in it.
    """
    venv = root / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


def command(root: Path, argv: list[str]) -> tuple[str, list[str], dict[str, str]]:
    """The interpreter to hand over to, its arguments, and the environment."""
    python = interpreter(root)
    source = str(root / "src")
    env = dict(os.environ)
    # Ahead of site-packages: the installed package is importable in this same
    # interpreter, and the working tree has to win.
    env["PYTHONPATH"] = (
        os.pathsep.join([source, env["PYTHONPATH"]]) if env.get("PYTHONPATH") else source
    )
    env[ENV] = str(root)
    return python, [python, "-m", "cloudmorrow.cli.main", *argv], env


def checkout() -> Path | None:
    """The checkout this process was handed over to, if it was.

    The variable says handed over; the code has to agree. One left behind in
    a shell — exported once, or inherited from a TUI that was started with
    the flag — would otherwise make the installed client call itself the
    checkout, and print the checkout's path under code that is not its own.
    """
    root = os.environ.get(ENV)
    if not root:
        return None
    path = Path(root)
    return path if running_from(path) else None


def handle(argv: list[str]) -> list[str]:
    """Take `--dev` out of the arguments, and act on it.

    Returns what is left for the CLI to parse — or never returns at all, having
    replaced this process with the checkout's.
    """
    if FLAG not in argv:
        return argv
    rest = [argument for argument in argv if argument != FLAG]

    # Already handed over: this *is* the checkout's code, so parse and get on
    # with it rather than handing over to ourselves for ever. A stale marker
    # — set, but not by the hand-over that started this process — is not that,
    # and must not stop the real one.
    if checkout() is not None:
        return rest
    os.environ.pop(ENV, None)

    root = find_checkout()
    if root is None:
        sys.exit(
            f"{FLAG} runs the cloudmorrow checkout you are standing in, and "
            f"{Path.cwd()} is not inside one."
        )
    if running_from(root):
        # Started from source already — the flag has nothing to change but the
        # label, which is worth setting so the TUI agrees with itself.
        os.environ[ENV] = str(root)
        return rest

    python, arguments, env = command(root, rest)
    os.execve(python, arguments, env)
