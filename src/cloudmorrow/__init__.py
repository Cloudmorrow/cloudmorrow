"""Cloudmorrow — a local cloud you install on your own hardware."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _installed_version

# Read back from the installed package, because the build wrote it there from
# the git tag — there is no number typed into this file to fall out of date.
# A deploy reinstalls whenever the commit moves, so this is current on a server.
try:
    __version__ = _installed_version("cloudmorrow")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0"

__all__ = ["__version__"]
