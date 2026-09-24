"""Shares over WebDAV: the part the server and the agent have in common.

A share is a name and a directory, served at `/dav/<name>/`. The server
serves the shares it holds; an agent serves the ones on its own machine.
Both hand WsgiDAV the same two things — which shares the caller may see,
and whether the caller is who they say — and everything else is here.

WsgiDAV does the protocol. What is ours:

- **who is asking.** Mounts speak HTTP Basic, so a `check_credentials`
  callable decides whether a username and password are good. The server
  checks them itself; an agent asks the server.
- **what they may see.** One provider, which turns `/<name>/rest` into the
  directory behind the caller's share of that name and nothing else. The
  root lists the caller's shares; another account's share does not exist,
  as far as this is concerned.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any, Protocol

from wsgidav.dav_error import HTTP_FORBIDDEN, HTTP_NOT_FOUND, DAVError
from wsgidav.dav_provider import DAVCollection, DAVProvider
from wsgidav.dc.base_dc import BaseDomainController
from wsgidav.fs_dav_provider import FileResource, FolderResource
from wsgidav.wsgidav_app import WsgiDAVApp

# Where the app is mounted; hrefs in every PROPFIND answer start with it.
MOUNT_PATH = "/dav"
REALM = "Cloudmorrow"


class Served(Protocol):
    """What the provider needs to know about a share: its name and directory."""

    name: str
    path: Any  # str or Path


class ShareSource(Protocol):
    """Where the provider asks which shares a caller has."""

    def shares_for(self, owner: str) -> list[Served]: ...

    def share_for(self, owner: str, name: str) -> Served | None: ...


class BasicDomainController(BaseDomainController):
    """Basic auth through the `check_credentials` callable. One realm, nothing anonymous."""

    def __init__(self, wsgidav_app: Any, config: dict) -> None:
        super().__init__(wsgidav_app, config)
        self._check: Callable[[str, str], bool] = config["cloudmorrow"]["check_credentials"]

    def get_domain_realm(self, path_info: str, environ: dict | None) -> str:
        return REALM

    def require_authentication(self, realm: str, environ: dict | None) -> bool:
        return True

    def basic_auth_user(self, realm: str, user_name: str, password: str, environ: dict) -> bool:
        return self._check(user_name, password)

    def supports_http_digest_auth(self) -> bool:
        # Digest needs the plain password on the server; there is a hash.
        return False


def _split(path: str) -> tuple[str, list[str]]:
    """`/name/a/b` → ('name', ['a', 'b']); the root → ('', [])."""
    parts = [part for part in path.split("/") if part]
    return (parts[0].lower(), parts[1:]) if parts else ("", [])


def _caller(environ: dict) -> str:
    return environ.get("wsgidav.auth.user_name") or ""


class SharesRoot(DAVCollection):
    """`/dav/`: the caller's shares, as folders. Read-only in itself."""

    def __init__(self, environ: dict) -> None:
        super().__init__("/", environ)

    def get_display_name(self) -> str:
        return "cloudmorrow"

    def get_member_names(self) -> list[str]:
        return [share.name for share in self.provider.shares_for(self.environ)]

    def get_member(self, name: str):
        return self.provider.get_resource_inst(f"/{name}", self.environ)

    def create_empty_resource(self, name: str):
        raise DAVError(HTTP_FORBIDDEN, "a share is made in Cloudmorrow, not here")

    def create_collection(self, name: str):
        raise DAVError(HTTP_FORBIDDEN, "a share is made in Cloudmorrow, not here")

    def delete(self):
        raise DAVError(HTTP_FORBIDDEN)

    def copy_move_single(self, dest_path: str, *, is_move: bool):
        raise DAVError(HTTP_FORBIDDEN)


class ShareFolder(FolderResource):
    """A directory inside a share — or the share itself, which stays put.

    The share's own directory is deleted, moved or copied through the API,
    where the rules about whose directory it is live; over WebDAV it is the
    one folder that cannot be. Everything inside it is an ordinary folder.
    """

    def __init__(self, path: str, environ: dict, file_path: str, share: Served | None) -> None:
        super().__init__(path, environ, file_path)
        self._share = share
        if share is not None:
            self.name = share.name

    def _pinned(self) -> None:
        if self._share is not None:
            raise DAVError(HTTP_FORBIDDEN, "the share itself is managed in Cloudmorrow")

    def support_recursive_delete(self) -> bool:
        # True, so a DELETE reaches this folder's own delete() first. Left at
        # the default, WsgiDAV deletes every child one by one before asking
        # the folder — and a DELETE on the share would empty it, then 403.
        return True

    def delete(self):
        self._pinned()
        super().delete()

    def copy_move_single(self, dest_path: str, *, is_move: bool):
        self._pinned()
        super().copy_move_single(dest_path, is_move=is_move)

    def move_recursive(self, dest_path: str):
        self._pinned()
        super().move_recursive(dest_path)


class SharesProvider(DAVProvider):
    """`/<share>/…` for whoever is signed in, and their shares at `/`.

    Built on WsgiDAV's own file and folder resources, which ask their provider
    for one thing — where a path is on disk — and that is the question this
    answers per caller rather than per configuration.
    """

    def __init__(self, source: ShareSource, *, fs_opts: dict | None = None) -> None:
        super().__init__()
        self.source = source
        self.readonly = False
        self.fs_opts = fs_opts or {"follow_symlinks": False}

    def __repr__(self) -> str:
        return "SharesProvider"

    # -- who sees what -----------------------------------------------------
    def shares_for(self, environ: dict) -> list[Served]:
        owner = _caller(environ)
        return self.source.shares_for(owner) if owner else []

    def share_for(self, environ: dict, name: str) -> Served | None:
        owner = _caller(environ)
        return self.source.share_for(owner, name) if owner and name else None

    # -- what WsgiDAV asks -------------------------------------------------
    def _loc_to_file_path(self, path: str, environ: dict | None = None) -> str:
        """The file behind *path*, or a DAVError. Never outside the share."""
        environ = environ or {}
        name, rest = _split(path)
        share = self.share_for(environ, name)
        if share is None:
            raise DAVError(HTTP_NOT_FOUND)
        root = str(share.path)
        file_path = os.path.abspath(os.path.join(root, *rest))
        if self.fs_opts.get("follow_symlinks"):
            inside = _within(root, file_path)
        else:
            inside = _within(os.path.realpath(root), os.path.realpath(file_path))
        if not inside:
            raise DAVError(HTTP_FORBIDDEN, "access outside the share is not allowed")
        return file_path

    def get_resource_inst(self, path: str, environ: dict):
        self._count_get_resource_inst += 1
        name, rest = _split(path)
        if not name:
            return SharesRoot(environ)
        share = self.share_for(environ, name)
        if share is None:
            return None
        file_path = self._loc_to_file_path(path, environ)
        if not os.path.exists(file_path):
            return None
        if not self.fs_opts.get("follow_symlinks") and os.path.islink(file_path):
            raise DAVError(HTTP_FORBIDDEN, "symlinks are not followed")
        if os.path.isdir(file_path):
            return ShareFolder(path, environ, file_path, share if not rest else None)
        return FileResource(path, environ, file_path)


def _within(root: str, candidate: str) -> bool:
    try:
        return os.path.commonpath([root, candidate]) == root
    except ValueError:
        return False


def build_app(source: ShareSource, check_credentials: Callable[[str, str], bool]) -> WsgiDAVApp:
    """The WSGI app that serves *source*'s shares at `/dav`, to whoever
    *check_credentials* lets in."""
    config = {
        "mount_path": MOUNT_PATH,
        "provider_mapping": {"/": SharesProvider(source)},
        "verbose": 1,
        "logging": {"enable": False},
        "http_authenticator": {
            "domain_controller": BasicDomainController,
            "accept_basic": True,
            "accept_digest": False,
            "default_to_digest": False,
        },
        "cloudmorrow": {"check_credentials": check_credentials},
        # Dead properties in memory: Finder and Explorer both like to leave a
        # few, and refusing them makes some clients give up on writing.
        "property_manager": True,
        "lock_storage": True,
        "suppress_version_info": True,
        "dir_browser": {
            "enable": True,
            "davmount": False,
            "davmount_links": False,
            "ms_sharepoint_support": False,
            "libre_office_support": False,
            "response_trailer": "",
        },
    }
    return WsgiDAVApp(config)
