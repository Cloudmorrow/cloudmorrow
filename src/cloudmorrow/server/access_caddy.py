"""Caddy on the box: the certificate for the cloud's real name, and TLS for it.

Public or private, a visitor's TLS ends on the box, in Caddy, never at the
relay. So when a name is claimed, renamed, or given back, Caddy has to be
told. The service cannot write /etc (ProtectSystem=strict) and cannot
restart Caddy, so the installer arranges two things once, as root:

* a directory the service owns and Caddy can read
  (`access_caddy_dir`, /var/lib/cloudmorrow-caddy, group caddy), and
* one line in /etc/caddy/Caddyfile: `import /var/lib/cloudmorrow-caddy/*.caddy`.

From then on the service writes `cloudmorrow.caddy` there — one site
block for `<name>.<zone>` — and asks Caddy's admin endpoint (localhost:2019)
to load the Caddyfile again, which picks it up. Caddy reads the same files
when it starts, so nothing is lost to a restart.

The certificate is the ordinary HTTP challenge when public access is on
(port 80 reaches the box through the tunnel). With only private access,
nothing on the internet can reach the box, so the site asks for the DNS
challenge through the control server's acme-dns endpoint, which needs
Caddy built with the `acmedns` module (the installer gets that build).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx

from cloudmorrow.server.access_control import Cloud
from cloudmorrow.server.config import ServerConfig

log = logging.getLogger("cloudmorrow.access.caddy")

SITE_FILE = "cloudmorrow.caddy"


def _quote(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def site_block(cloud: Cloud, config: ServerConfig, control: str) -> str:
    """The Caddyfile site for the cloud's real name, reverse-proxying to the server."""
    upstream = f"{'127.0.0.1' if config.host in ('0.0.0.0', '::', '') else config.host}:{config.port}"
    lines = [
        "# Written by Cloudmorrow (Administration -> Access). It is rewritten when",
        "# the name changes; edit /etc/caddy/Caddyfile instead.",
        f"{cloud.host} {{",
    ]
    if not cloud.public and cloud.acme:
        acme = cloud.acme
        lines += [
            "\ttls {",
            "\t\tdns acmedns {",
            f"\t\t\tusername {_quote(acme.get('username', ''))}",
            f"\t\t\tpassword {_quote(acme.get('password', ''))}",
            f"\t\t\tsubdomain {_quote(acme.get('subdomain', ''))}",
            # The register call says where updates go; the control server's
            # own /v1/acme-dns when it does not.
            f"\t\t\tserver_url {_quote(acme.get('server_url') or control.rstrip('/') + '/v1/acme-dns')}",
            "\t\t}",
            "\t}",
        ]
    lines += [f"\treverse_proxy {upstream}", "}", ""]
    return "\n".join(lines)


class Caddy:
    """Writes the site file and reloads Caddy. Every failure is a sentence, never a crash."""

    def __init__(self, config: ServerConfig, http: httpx.Client | None = None) -> None:
        self.config = config
        self.http = http
        self.error = ""
        self.written = ""

    @property
    def site_path(self) -> Path:
        return Path(self.config.access_caddy_dir) / SITE_FILE

    def available(self) -> bool:
        return Path(self.config.access_caddy_dir).is_dir()

    def status(self) -> dict:
        return {
            "configured": self.available(),
            "site": str(self.site_path) if self.site_path.exists() else "",
            "error": self.error,
        }

    def apply(self, cloud: Cloud | None, control: str) -> bool:
        """Make the site file say what *cloud* needs (nothing, for None), and reload."""
        if not self.available():
            self.error = (
                f"Caddy is not set up for Cloudmorrow on this box ({self.config.access_caddy_dir} "
                "is missing); the server installer does it: sudo sh install-server.sh"
            )
            return False
        wanted = site_block(cloud, self.config, control) if cloud and cloud.reachable else ""
        try:
            current = self.site_path.read_text(encoding="utf-8") if self.site_path.exists() else ""
            if wanted == current:
                self.error = ""
                return True
            if wanted:
                tmp = self.site_path.with_name(f".{SITE_FILE}.tmp")
                # 0640 with the directory's group (caddy): the acme-dns
                # password is in it, and only Caddy needs to read it.
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(wanted)
                os.replace(tmp, self.site_path)
            else:
                self.site_path.unlink(missing_ok=True)
        except OSError as exc:
            self.error = f"cannot write {self.site_path}: {exc}"
            return False
        self.written = wanted
        return self.reload()

    def reload(self) -> bool:
        """Ask Caddy to load its Caddyfile again, through its admin endpoint."""
        try:
            caddyfile = Path(self.config.access_caddyfile).read_text(encoding="utf-8")
        except OSError as exc:
            self.error = f"cannot read {self.config.access_caddyfile}: {exc}"
            return False
        client = self.http or httpx.Client(timeout=15)
        try:
            response = client.post(
                self.config.access_caddy_admin.rstrip("/") + "/load",
                content=caddyfile.encode("utf-8"),
                headers={"Content-Type": "text/caddyfile"},
            )
        except httpx.HTTPError as exc:
            self.error = f"Caddy is not answering at {self.config.access_caddy_admin}: {exc}"
            return False
        finally:
            if self.http is None:
                client.close()
        if response.status_code >= 400:
            self.error = f"Caddy would not load the site: {response.text.strip()[:300]}"
            return False
        self.error = ""
        log.info("Caddy reloaded with the site for the cloud's name")
        return True
