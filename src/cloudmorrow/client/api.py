"""Async HTTP client for the Cloudmorrow API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from cloudmorrow.client.config import ClientConfig, StoredCredentials
from cloudmorrow.transport import InsecureUrlError, check_url

TIMEOUT = httpx.Timeout(10.0, connect=5.0)
# A deploy is a git fetch, a pip install and a wheel build. It is the one call
# that is allowed to take minutes.
DEPLOY_TIMEOUT = httpx.Timeout(600.0, connect=5.0)
# A picture over a slow link.
UPLOAD_TIMEOUT = httpx.Timeout(120.0, connect=5.0)


class ApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class AuthError(ApiError):
    """Credentials are missing, wrong or expired."""


class ConflictError(ApiError):
    """The note changed on the server since we last read it."""

    def __init__(self, message: str, *, rev: str = "", content: str = "") -> None:
        super().__init__(message, status_code=409)
        self.rev = rev
        self.content = content


@dataclass(slots=True)
class Session:
    username: str
    access_token: str
    expires_at: str = ""


class CloudmorrowClient:
    """Everything the TUI needs to talk to the server."""

    def __init__(
        self, config: ClientConfig, token: str | None = None, vault: str | None = None
    ) -> None:
        self.config = config
        self._token = token
        # The vault every secrets call names when it does not name one
        # itself: the CLI sets it from its config, so `cm secret get KEY`
        # works in the vault you chose. The TUI leaves it None and passes
        # `vault=` where it means one — there is no selected vault there.
        self.vault = vault
        try:
            check_url(config.api_url, allow_insecure=config.allow_insecure_http)
        except InsecureUrlError as exc:
            raise ApiError(str(exc)) from exc
        self._client = httpx.AsyncClient(
            base_url=config.api_url,
            timeout=TIMEOUT,
            verify=config.verify_tls,
            headers={"User-Agent": "cloudmorrow-tui"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def token(self) -> str | None:
        return self._token

    def _headers(self, vault: str | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        scope = vault or self.vault
        if scope:
            headers["X-Cloudmorrow-Vault"] = scope
        return headers

    async def _request(
        self,
        method: str,
        url: str,
        *,
        vault: str | None = None,
        headers_extra: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """One call. *vault* names the vault for this call alone."""
        headers = {**self._headers(vault), **(headers_extra or {})}
        try:
            response = await self._client.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise ApiError(f"cannot reach {self.config.api_url}: {exc}") from exc
        if response.status_code == 401:
            # The server's own wording ("invalid username or password",
            # "token expired") is more useful than a generic message.
            raise AuthError(str(_detail(response)), status_code=401)
        if response.status_code == 409:
            detail = _detail(response)
            if isinstance(detail, dict) and detail.get("error") == "conflict":
                raise ConflictError(
                    str(detail.get("message", "conflict")),
                    rev=str(detail.get("rev", "")),
                    content=str(detail.get("content", "")),
                )
            raise ApiError(str(detail), status_code=409, payload=detail)
        if response.status_code >= 400:
            raise ApiError(str(_detail(response)), status_code=response.status_code)
        return response

    # -- auth --------------------------------------------------------------
    async def login(self, username: str, password: str) -> Session:
        response = await self._request(
            "POST", "/api/auth/login", json={"username": username, "password": password}
        )
        data = response.json()
        self._token = data["access_token"]
        return Session(
            username=data["user"]["username"],
            access_token=data["access_token"],
            expires_at=str(data.get("expires_at", "")),
        )

    async def me(self) -> dict:
        return (await self._request("GET", "/api/auth/me")).json()

    async def change_password(self, current: str, new: str) -> None:
        """Set a new password. The server answers 403 when *current* is wrong."""
        await self._request(
            "POST",
            "/api/auth/password",
            json={"current_password": current, "new_password": new},
        )

    async def health(self) -> dict:
        return (await self._request("GET", "/api/health")).json()

    async def client_release(self) -> dict:
        """The package this server hands out, for `cloudmorrow update`."""
        return (await self._request("GET", "/api/client")).json()

    async def update_server(
        self, *, branch: str | None = None, force: bool = False, restart: bool = True
    ) -> dict:
        """Deploy the server from git. Admin only, and it restarts underneath you."""
        return (
            await self._request(
                "POST",
                "/api/server/update",
                json={"branch": branch, "force": force, "restart": restart},
                timeout=DEPLOY_TIMEOUT,
            )
        ).json()

    # -- administration ----------------------------------------------------
    async def users(self) -> list[dict]:
        """Every account on the server. Admin only."""
        return (await self._request("GET", "/api/users")).json()

    async def create_user(
        self,
        username: str,
        password: str,
        *,
        display_name: str = "",
        role: str = "user",
        user_type: str = "human",
    ) -> dict:
        return (
            await self._request(
                "POST",
                "/api/users",
                json={
                    "username": username,
                    "password": password,
                    "display_name": display_name,
                    "role": role,
                    "user_type": user_type,
                },
            )
        ).json()

    async def update_user(self, username: str, **fields: object) -> dict:
        """Change one account: display_name, role, user_type, password, is_active."""
        return (
            await self._request("PATCH", f"/api/users/{username}", json=fields)
        ).json()

    async def delete_user(self, username: str) -> None:
        await self._request("DELETE", f"/api/users/{username}")

    async def features(self) -> list[dict]:
        """What this server offers, and what an admin has switched off."""
        return (await self._request("GET", "/api/server/features")).json()

    async def set_feature(self, key: str, enabled: bool) -> dict:
        return (
            await self._request(
                "PATCH", f"/api/server/features/{key}", json={"enabled": enabled}
            )
        ).json()

    async def my_features(self) -> list[dict]:
        """What this account may switch, with its own answer on each.

        Only what the server offers, so this is the list a client draws its
        tabs from — one that is off here is off for this person, whichever
        of the two switches did it.
        """
        return (await self._request("GET", "/api/me/features")).json()

    async def set_my_feature(self, key: str, enabled: bool) -> dict:
        return (
            await self._request("PATCH", f"/api/me/features/{key}", json={"enabled": enabled})
        ).json()

    # -- notes -------------------------------------------------------------
    async def tree(self) -> dict:
        return (await self._request("GET", "/api/notes/tree")).json()

    async def read(self, path: str) -> dict:
        return (await self._request("GET", f"/api/notes/file/{path}")).json()

    async def write(self, path: str, content: str, rev: str | None = None) -> dict:
        return (
            await self._request(
                "PUT", f"/api/notes/file/{path}", json={"content": content, "rev": rev}
            )
        ).json()

    async def create_note(self, path: str, content: str = "") -> dict:
        return (
            await self._request("POST", "/api/notes/file", json={"path": path, "content": content})
        ).json()

    async def create_dir(self, path: str) -> dict:
        return (await self._request("POST", "/api/notes/dir", json={"path": path})).json()

    async def delete(self, path: str, *, recursive: bool = False) -> None:
        await self._request("DELETE", f"/api/notes/{path}", params={"recursive": recursive})

    async def move(self, src: str, dest: str) -> dict:
        return (
            await self._request("POST", "/api/notes/move", json={"src": src, "dest": dest})
        ).json()

    async def search(self, query: str) -> dict:
        return (await self._request("GET", "/api/notes/search", params={"q": query})).json()

    async def upload_image(self, data: bytes, *, filename: str = "") -> dict:
        """Keep a picture with the notes. Answers with the `img/<name>` a note writes."""
        return (
            await self._request(
                "POST",
                "/api/notes/img",
                content=data,
                params={"filename": filename},
                timeout=UPLOAD_TIMEOUT,
            )
        ).json()

    async def image(self, name: str) -> bytes:
        response = await self._request("GET", f"/api/notes/img/{name}", timeout=UPLOAD_TIMEOUT)
        return response.content

    # -- secrets -----------------------------------------------------------
    async def secrets(
        self,
        environment: str | None = None,
        *,
        reveal: bool = False,
        vault: str | None = None,
    ) -> list[dict]:
        """Secrets in one environment, or in all of them when it is None.

        Values come back only with *reveal*; otherwise each secret is described
        by its length and fingerprint.
        """
        params: dict[str, str | bool] = {"reveal": reveal}
        if environment:
            params["env"] = environment
        return (
            await self._request("GET", "/api/secrets", params=params, vault=vault)
        ).json()

    async def secret_vaults(self) -> list[dict]:
        """The vaults that hold something, whichever one is selected."""
        return (await self._request("GET", "/api/secrets/vaults")).json()

    async def secret_environments(self, *, vault: str | None = None) -> list[dict]:
        return (
            await self._request("GET", "/api/secrets/environments", vault=vault)
        ).json()

    async def read_secret(
        self, key: str, environment: str, *, vault: str | None = None
    ) -> dict:
        return (
            await self._request(
                "GET",
                f"/api/secrets/item/{key}",
                params={"env": environment},
                vault=vault,
            )
        ).json()

    async def write_secret(
        self, key: str, value: str, environment: str, *, vault: str | None = None
    ) -> dict:
        return (
            await self._request(
                "PUT",
                f"/api/secrets/item/{key}",
                json={"value": value, "environment": environment},
                vault=vault,
            )
        ).json()

    async def delete_secret(
        self, key: str, environment: str, *, vault: str | None = None
    ) -> None:
        await self._request(
            "DELETE",
            f"/api/secrets/item/{key}",
            params={"env": environment},
            vault=vault,
        )

    async def import_secrets(
        self,
        entries: dict[str, str],
        environment: str,
        *,
        prune: bool = False,
        overwrite: bool = True,
        dry_run: bool = False,
        filename: str = "",
        vault: str | None = None,
    ) -> dict:
        return (
            await self._request(
                "POST",
                "/api/secrets/import",
                json={
                    "entries": entries,
                    "environment": environment,
                    "prune": prune,
                    "overwrite": overwrite,
                    "dry_run": dry_run,
                    # What it was called here, so a clone elsewhere can match it.
                    "filename": filename,
                },
                vault=vault,
            )
        ).json()

    async def export_secrets(
        self, environment: str, *, vault: str | None = None
    ) -> dict[str, str]:
        """Every value in one environment, as plain pairs to render locally."""
        return (
            await self._request(
                "GET",
                "/api/secrets/export",
                params={"env": environment, "format": "json"},
                vault=vault,
            )
        ).json()

    async def delete_environment(
        self, environment: str, *, vault: str | None = None
    ) -> dict:
        return (
            await self._request(
                "DELETE", f"/api/secrets/environment/{environment}", vault=vault
            )
        ).json()

    async def delete_vault(self, vault: str) -> dict:
        return (await self._request("DELETE", f"/api/secrets/vault/{vault}")).json()

    # -- Quills, and the records of every datamodel -------------------------
    async def quills(self) -> list[dict]:
        """Every installed Quill, with its screens and its datamodels in full."""
        return (await self._request("GET", "/api/quills")).json()

    async def quill_catalog(self) -> dict:
        return (await self._request("GET", "/api/quills/catalog")).json()

    async def plan_quill(self, *, id: str = "", source: str = "", ref: str = "") -> dict:
        """What installing a Quill would add, without installing it."""
        body = {"id": id, "source": source, "ref": ref}
        return (await self._request("POST", "/api/quills/plan", json=body)).json()

    async def install_quill(self, *, id: str = "", source: str = "", ref: str = "") -> dict:
        body = {"id": id, "source": source, "ref": ref}
        return (await self._request("POST", "/api/quills", json=body)).json()

    async def upload_quill(self, data: bytes, *, plan_only: bool = False) -> dict:
        """Install a Quill from a .tar.gz of its folder — or, with plan_only, only say what it adds."""
        response = await self._request(
            "POST", "/api/quills/upload", params={"plan_only": str(plan_only).lower()},
            content=data, headers_extra={"Content-Type": "application/gzip"},
        )
        return response.json()

    async def uninstall_quill(self, quill_id: str) -> None:
        await self._request("DELETE", f"/api/quills/{quill_id}")

    async def datamodels(self) -> list[dict]:
        return (await self._request("GET", "/api/datamodels")).json()

    async def records(
        self, model: str, *, last: int | None = None, since: str | None = None, **where: object
    ) -> list[dict]:
        """Every record of *model* you have, filtered on indexed fields, in order.

        *last* keeps the newest so many; *since* only what changed at or after it.
        """
        params = {k: ("true" if v is True else "false" if v is False else v) for k, v in where.items()}
        if last is not None:
            params["_last"] = last
        if since:
            params["_since"] = since
        return (await self._request("GET", f"/api/records/{model}", params=params)).json()

    async def record(self, model: str, record_id: str) -> dict:
        return (await self._request("GET", f"/api/records/{model}/{record_id}")).json()

    async def create_record(
        self,
        model: str,
        fields: dict,
        *,
        index: int | None = None,
        scope: str | None = None,
        members: list[str] | None = None,
        unique: bool = False,
    ) -> dict:
        """Make a record. A space takes a scope, a shared one its people.

        With *unique*, the space with exactly you and *members* in it (and
        the same indexed fields) comes back if there is one already.
        """
        body: dict = {"fields": fields}
        if index is not None:
            body["index"] = index
        if scope:
            body["scope"] = scope
        if members:
            body["members"] = list(members)
        if unique:
            body["unique"] = True
        return (await self._request("POST", f"/api/records/{model}", json=body)).json()

    async def update_record(
        self, model: str, record_id: str, fields: dict, *, rev: int | None = None
    ) -> dict:
        body: dict = {"fields": fields}
        if rev is not None:
            body["rev"] = rev
        return (await self._request("PATCH", f"/api/records/{model}/{record_id}", json=body)).json()

    async def move_record(
        self, model: str, record_id: str, fields: dict, index: int | None = None
    ) -> dict:
        body = {"fields": fields, "index": index}
        return (
            await self._request("POST", f"/api/records/{model}/{record_id}/move", json=body)
        ).json()

    async def delete_record(self, model: str, record_id: str) -> None:
        await self._request("DELETE", f"/api/records/{model}/{record_id}")

    # -- the people in a space (a shared calendar, a channel) ------------------
    async def people(self) -> list[dict]:
        """Everybody on the server a space could be shared with."""
        return (await self._request("GET", "/api/people")).json()

    async def add_member(self, model: str, space_id: str, username: str) -> dict:
        """Put somebody in a shared space. Returns the space, members and all."""
        return (
            await self._request(
                "POST", f"/api/records/{model}/{space_id}/members", json={"username": username}
            )
        ).json()

    async def remove_member(self, model: str, space_id: str, username: str) -> None:
        """Take somebody out of a shared space; with your own name, leave it."""
        await self._request("DELETE", f"/api/records/{model}/{space_id}/members/{username}")

    async def mark_seen(self, model: str, space_id: str) -> None:
        """You have looked in this space: what is in it is not unread any more."""
        await self._request("POST", f"/api/records/{model}/{space_id}/seen")

    # A datamodel's folders and attachments, where its backend keeps them
    # (the model's `can` says so): a note's folders, and its pictures.
    async def record_folders(self, model: str) -> list[dict]:
        return (await self._request("GET", f"/api/records/{model}/_folders")).json()

    async def make_record_folder(self, model: str, path: str) -> dict:
        return (
            await self._request("POST", f"/api/records/{model}/_folders", json={"path": path})
        ).json()

    async def move_record_folder(self, model: str, path: str, to: str) -> dict:
        body = {"path": path, "to": to}
        return (await self._request("PATCH", f"/api/records/{model}/_folders", json=body)).json()

    async def delete_record_folder(self, model: str, path: str) -> None:
        await self._request("DELETE", f"/api/records/{model}/_folders", params={"path": path})

    async def attach(self, model: str, data: bytes, *, filename: str = "") -> dict:
        """Keep a file beside *model*'s records: `{name, path, …}`, `path` for Markdown."""
        return (
            await self._request(
                "POST", f"/api/records/{model}/_attachments", content=data,
                params={"filename": filename}, timeout=UPLOAD_TIMEOUT,
            )
        ).json()

    async def attachment(self, model: str, name: str) -> bytes:
        response = await self._request(
            "GET", f"/api/records/{model}/_attachments/{name}", timeout=UPLOAD_TIMEOUT
        )
        return response.content

    # The bytes beside a record, for a datamodel that keeps some: a file's.
    async def record_content(self, model: str, record_id: str) -> bytes:
        response = await self._request(
            "GET", f"/api/records/{model}/{record_id}/content", timeout=UPLOAD_TIMEOUT
        )
        return response.content

    async def record_thumb(self, model: str, record_id: str, *, size: int = 256) -> bytes:
        """A JPEG with its long edge at *size* or so; a 415 when the server
        cannot make one of that record's bytes."""
        response = await self._request(
            "GET", f"/api/records/{model}/{record_id}/thumb", params={"size": size}
        )
        return response.content

    async def upload_record(self, model: str, fields: dict, data: bytes) -> dict:
        """A new record from bytes: *fields* say where it goes and what it is called."""
        response = await self._request(
            "POST",
            f"/api/records/{model}/upload",
            params={k: str(v) for k, v in fields.items()},
            content=data,
            headers_extra={"Content-Type": "application/octet-stream"},
            timeout=UPLOAD_TIMEOUT,
        )
        return response.json()

    # -- fileshares --------------------------------------------------------
    async def shares(self) -> list[dict]:
        return (await self._request("GET", "/api/shares")).json()

    async def get_share(self, name: str) -> dict:
        return (await self._request("GET", f"/api/shares/{name}")).json()

    async def share_folders(self) -> dict:
        """Your Shares directory on the server, and the folders in it that are
        not shares yet: {"directory": ..., "folders": [...]}. Admins only."""
        return (await self._request("GET", "/api/shares/folders")).json()

    async def create_share(
        self,
        name: str,
        *,
        kind: str = "server",
        path: str | None = None,
        machine: str | None = None,
        description: str = "",
    ) -> dict:
        """A new share.

        A server share (admins only) is the folder of that name in your Shares
        directory on the server, made if it is not there; it takes no *path*.
        A machine share serves *path* on the agent called *machine*, and
        anyone may make one.
        """
        payload: dict[str, str] = {"name": name, "kind": kind, "description": description}
        if path:
            payload["path"] = path
        if machine:
            payload["machine"] = machine
        return (await self._request("POST", "/api/shares", json=payload)).json()

    async def delete_share(self, name: str, *, remove_files: bool = False) -> None:
        await self._request(
            "DELETE", f"/api/shares/{name}", params={"remove_files": remove_files}
        )

    # What is in a server share, the way the web app asks: a folder's
    # listing, a file, and a small copy of a picture for a grid or a panel.
    async def share_listing(self, name: str, path: str = "") -> dict:
        """{"share", "path", "entries": [{name, is_dir, size, modified, mime}]}."""
        return (
            await self._request("GET", f"/api/shares/{name}/ls", params={"path": path})
        ).json()

    async def share_file(self, name: str, path: str) -> bytes:
        response = await self._request(
            "GET", f"/api/shares/{name}/file", params={"path": path}, timeout=UPLOAD_TIMEOUT
        )
        return response.content

    async def share_thumb(self, name: str, path: str, *, size: int = 256) -> bytes:
        """A JPEG with its long edge at *size* or so; a 415 when the server
        cannot make one of that file."""
        response = await self._request(
            "GET", f"/api/shares/{name}/thumb", params={"path": path, "size": size}
        )
        return response.content

    # -- agents ------------------------------------------------------------
    async def agents(self) -> list[dict]:
        return (await self._request("GET", "/api/agents")).json()

    async def enroll_self(
        self,
        *,
        name: str,
        hostname: str = "",
        platform: str = "",
        version: str = "",
        capabilities: list[str] | None = None,
    ) -> dict:
        """Enrol the machine we are signed in from, as the signed-in user."""
        return (
            await self._request(
                "POST",
                "/api/agents/enroll-self",
                json={
                    "name": name,
                    "hostname": hostname,
                    "platform": platform,
                    "version": version,
                    "capabilities": capabilities or [],
                },
            )
        ).json()

    async def enroll_token(self, label: str = "") -> dict:
        return (
            await self._request(
                "POST", "/api/agents/enroll-token", json={"label": label, "ttl_minutes": 60}
            )
        ).json()

    async def delete_agent(self, agent_id: int) -> None:
        await self._request("DELETE", f"/api/agents/{agent_id}")

    async def create_job(self, agent_id: int, job_type: str, payload: dict | None = None) -> dict:
        return (
            await self._request(
                "POST",
                f"/api/agents/{agent_id}/jobs",
                json={"type": job_type, "payload": payload or {}},
            )
        ).json()

    async def jobs(self, agent_id: int, limit: int = 25) -> list[dict]:
        return (
            await self._request(
                "GET", f"/api/agents/{agent_id}/jobs", params={"limit": limit}
            )
        ).json()

    # -- config sync -------------------------------------------------------
    async def set_agent_sync(self, agent_id: int, bundles: list[str]) -> dict:
        """Switch config syncing on or off for a machine. [] switches it off."""
        return (
            await self._request(
                "PATCH", f"/api/agents/{agent_id}/sync", json={"sync_bundles": bundles}
            )
        ).json()

    async def config_bundle(self, bundle: str) -> dict:
        """One bundle: its revision, who claimed it, and who is keeping it."""
        return (await self._request("GET", f"/api/config/{bundle}")).json()

    async def config_bundles(self) -> list[dict]:
        return (await self._request("GET", "/api/config")).json()

    async def forget_config_bundle(self, bundle: str) -> dict:
        """Unclaim it, so the next machine to switch syncing on decides again."""
        return (await self._request("DELETE", f"/api/config/{bundle}")).json()

    # -- notifications -----------------------------------------------------
    async def notifications(self, *, limit: int = 50, unread: bool = False) -> list[dict]:
        return (
            await self._request(
                "GET", "/api/notifications", params={"limit": limit, "unread": unread}
            )
        ).json()

    async def mark_notifications_read(self, ids: list[int] | None = None) -> dict:
        return (
            await self._request("POST", "/api/notifications/read", json={"ids": ids})
        ).json()


def _detail(response: httpx.Response) -> Any:
    try:
        payload = response.json()
    except ValueError:
        return response.text or f"HTTP {response.status_code}"
    if isinstance(payload, dict) and "detail" in payload:
        return payload["detail"]
    return payload


def client_from_credentials(
    config: ClientConfig, credentials: StoredCredentials | None
) -> CloudmorrowClient:
    token = credentials.access_token if credentials else None
    return CloudmorrowClient(config, token=token, vault=config.vault or None)
