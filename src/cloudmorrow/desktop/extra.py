"""The `desktop` extra: whether this copy has it, and the requirement that adds it.

The desktop app's dependencies (pywebview, and Qt on Linux) are an extra,
because a server, a NAS or a machine reached over ssh has no use for a
window and every use for the hundred megabytes it would not download. So
install.sh adds the extra where there is a desktop, and `cloudmorrow update`
keeps it where it was added. Both ask this, and the server's install route
does too, so it is standard library only.
"""

from __future__ import annotations

import importlib.util
import re

EXTRA = "desktop"
_REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[([^\]]*)\])?(.*)$", re.DOTALL)


def installed() -> bool:
    """Whether the desktop app's dependencies are here, without importing a GUI."""
    return importlib.util.find_spec("webview") is not None


def with_extra(spec: str, extra: str = EXTRA) -> str:
    """The same requirement with one more extra: `cloudmorrow[tui,agent] @ …/x.whl`
    becomes `cloudmorrow[tui,agent,desktop] @ …/x.whl`.

    A spec that is not a requirement at all (a bare path, say) is left as
    it is, and installing it then only adds what is already there.
    """
    match = _REQUIREMENT.match(spec)
    if match is None:
        return spec
    name, extras, rest = match.groups()
    names = [part.strip() for part in (extras or "").split(",") if part.strip()]
    if extra not in names:
        names.append(extra)
    return f"{name}[{','.join(names)}]{rest}"
