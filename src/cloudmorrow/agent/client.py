"""HTTP client the agent uses to talk to the Cloudmorrow server."""

from __future__ import annotations

import httpx

from cloudmorrow import __version__
from cloudmorrow.agent.config import AgentConfig
from cloudmorrow.transport import InsecureUrlError, check_url

TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class AgentApiError(RuntimeError):
    def __init__(
        self, message: str, *, status_code: int | None = None, payload: object = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        # The server's own body, for the callers that act on what is in it —
        # a stale push is told the revision it should have been working from.
        self.payload = payload


class AgentClient:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        try:
            check_url(config.server_url, allow_insecure=config.allow_insecure_http)
        except InsecureUrlError as exc:
            raise AgentApiError(str(exc)) from exc
        self._client = httpx.Client(
            base_url=config.server_url,
            timeout=TIMEOUT,
            verify=config.verify_tls,
            headers={"User-Agent": f"cloudmorrow-agent/{__version__}"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> AgentClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _headers(self, authenticated: bool = True) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.agent_token}"} if authenticated else {}

    def _check(self, response: httpx.Response) -> dict | None:
        if response.status_code >= 400:
            detail = _detail(response)
            raise AgentApiError(str(detail), status_code=response.status_code, payload=detail)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def _post(self, url: str, payload: dict, *, authenticated: bool = True) -> dict | None:
        try:
            response = self._client.post(
                url, json=payload, headers=self._headers(authenticated)
            )
        except httpx.HTTPError as exc:
            raise AgentApiError(f"cannot reach {self.config.server_url}: {exc}") from exc
        return self._check(response)

    def _get(self, url: str) -> dict | None:
        try:
            response = self._client.get(url, headers=self._headers())
        except httpx.HTTPError as exc:
            raise AgentApiError(f"cannot reach {self.config.server_url}: {exc}") from exc
        return self._check(response)

    def enroll(self, enrollment_token: str, name: str, hostname: str, platform: str) -> dict:
        payload = {
            "enrollment_token": enrollment_token,
            "name": name,
            "hostname": hostname,
            "platform": platform,
            "version": __version__,
            "capabilities": self.config.capabilities,
        }
        return self._post("/api/agent/enroll", payload, authenticated=False) or {}

    def heartbeat(self, hostname: str, platform: str, *, dav_base: str = "") -> dict:
        payload = {
            "hostname": hostname,
            "platform": platform,
            "version": __version__,
            "capabilities": self.config.capabilities,
            # Where this machine serves its shares; "" says it serves nothing.
            "dav_base": dav_base,
        }
        return self._post("/api/agent/heartbeat", payload) or {}

    def check_credentials(self, username: str, password: str) -> bool:
        """Whether a mount of one of this machine's shares may come in."""
        answer = self._post(
            "/api/agent/credentials", {"username": username, "password": password}
        )
        return bool(answer and answer.get("valid"))

    def claim_job(self) -> dict | None:
        return self._post("/api/agent/jobs/claim", {})

    def report(self, job_id: int, status: str, result: dict) -> None:
        self._post(f"/api/agent/jobs/{job_id}/result", {"status": status, "result": result})

    # -- config bundles ----------------------------------------------------
    def config_state(self, bundle: str) -> dict:
        """The manifest: revision and hashes, without the contents."""
        return self._get(f"/api/agent/config/{bundle}") or {}

    def config_files(self, bundle: str) -> dict:
        """The whole bundle, contents and all."""
        return self._get(f"/api/agent/config/{bundle}/files") or {}

    def push_config(
        self, bundle: str, files: list[dict], *, base_revision: int | None
    ) -> dict:
        """Offer this machine's copy. 409 means somebody else got there first."""
        return (
            self._post(
                f"/api/agent/config/{bundle}",
                {"files": files, "base_revision": base_revision},
            )
            or {}
        )

    def notify(self, *, kind: str, title: str, body: str = "") -> dict:
        return self._post(
            "/api/agent/notifications", {"kind": kind, "title": title, "body": body}
        ) or {}


def _detail(response: httpx.Response) -> object:
    try:
        payload = response.json()
    except ValueError:
        return response.text or f"HTTP {response.status_code}"
    if isinstance(payload, dict) and "detail" in payload:
        return payload["detail"]
    return payload
