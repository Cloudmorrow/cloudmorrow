"""Caddy on the box: the certificate for the cloud's real name, and TLS for it.

A linked cloud is reached at `https://<name>.<zone>`, by its devices on the
mesh and by those at home, and TLS ends on the box, in Caddy. So when the
box is linked, renamed on the website, or unlinked, Caddy has to be told.
The service cannot write /etc (ProtectSystem=strict) and cannot restart
Caddy, so the installer arranges two things once, as root:

* a directory the service owns and Caddy can read
  (`access_caddy_dir`, /var/lib/cloudmorrow-caddy, group caddy), and
* one line in /etc/caddy/Caddyfile: `import /var/lib/cloudmorrow-caddy/*.caddy`.

From then on the service writes `cloudmorrow.caddy` there — one site
block for `<name>.<zone>` — and asks Caddy's admin endpoint (localhost:2019)
to load the Caddyfile again, which picks it up. Caddy reads the same files
when it starts, so nothing is lost to a restart.

Nothing on the internet reaches the box, so the certificate is always the
DNS challenge, through the relay's acme-dns endpoint, with the account the
link handed over (`acme_dns`). That needs Caddy built with the `acmedns`
module, which the installer gets. Let's Encrypt first, ZeroSSL when that
fails (`site_block`).
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


def upstream_host(config: ServerConfig) -> str:
    """Where Caddy finds the server: loopback when it listens there (or everywhere), else its first address."""
    hosts = config.hosts
    if hosts[0] in ("0.0.0.0", "::"):
        return "127.0.0.1"
    local = [h for h in hosts if h in ("127.0.0.1", "localhost", "::1")]
    host = (local or hosts)[0]
    return f"[{host}]" if ":" in host else host


# ZeroSSL's ACME endpoint: the second issuer, for when Let's Encrypt's weekly
# limit for the zone is used up. Caddy fetches its EAB credentials itself,
# from an email address, which it needs.
ZEROSSL = "https://acme.zerossl.com/v2/DV90"

# Where Caddy looks names up for the challenge. Not the box's own resolver:
# a container's resolv.conf can list servers it cannot reach (a tailnet's
# fd7a:…::53 in an LXC), and Caddy gives up on the first of them.
RESOLVERS = ("1.1.1.1", "8.8.8.8")
# And no waiting to see the record from here at all: a home router that
# intercepts DNS, whatever server was asked, keeps answering "no such
# record" from its cache long after the relay has published it. The relay
# answers only once the record is at Cloudflare, which serves it within
# seconds; Let's Encrypt looks from its own side. So: a fixed wait.
PROPAGATION_DELAY = "30s"


def _issuer(acme: dict, control: str, *, directory: str = "", email: str = "") -> list[str]:
    """One `issuer acme` block, proving the name by DNS through the relay's acme-dns."""
    lines = ["\t\tissuer acme {"]
    if directory:
        lines.append(f"\t\t\tdir {directory}")
    if email:
        lines.append(f"\t\t\temail {_quote(email)}")
    lines += [
        "\t\t\tdns acmedns {",
        f"\t\t\t\tusername {_quote(acme.get('username', ''))}",
        f"\t\t\t\tpassword {_quote(acme.get('password', ''))}",
        f"\t\t\t\tsubdomain {_quote(acme.get('subdomain', ''))}",
        # The link says where updates go; the relay's own /v1/acme-dns when it does not.
        f"\t\t\t\tserver_url {_quote(acme.get('server_url') or control.rstrip('/') + '/v1/acme-dns')}",
        "\t\t\t}",
        f"\t\t\tresolvers {' '.join(RESOLVERS)}",
        f"\t\t\tpropagation_delay {PROPAGATION_DELAY}",
        "\t\t\tpropagation_timeout -1",
        "\t\t}",
    ]
    return lines


def site_block(cloud: Cloud, config: ServerConfig, control: str) -> str:
    """The Caddyfile site for the cloud's real name, reverse-proxying to the server.

    Two issuers, tried in order, both by the DNS challenge: Let's Encrypt,
    then ZeroSSL (`access_acme_fallback`, which needs `access_acme_email`).
    Every linked cloud's name is under one zone, and Let's Encrypt allows a
    zone only so many new certificates a week; the second keeps new clouds
    getting one when that runs out.
    """
    upstream = f"{upstream_host(config)}:{config.port}"
    email = (config.access_acme_email or "").strip()
    lines = [
        "# Written by Cloudmorrow (Administration -> Access). It is rewritten when",
        "# the name changes; edit /etc/caddy/Caddyfile instead.",
        f"{cloud.host} {{",
    ]
    if cloud.acme:
        lines.append("\ttls {")
        lines += _issuer(cloud.acme, control, email=email)
        if config.access_acme_fallback and email:
            lines += _issuer(cloud.acme, control, directory=ZEROSSL, email=email)
        elif config.access_acme_fallback:
            lines.append("\t\t# ZeroSSL, the fallback, needs an email: access_acme_email in server.toml.")
        lines.append("\t}")
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
            if cloud is None:
                # Nothing to hold, and nowhere to hold it: all is as it should be.
                self.error = ""
                return True
            self.error = (
                f"Caddy is not set up for Cloudmorrow on this box ({self.config.access_caddy_dir} "
                "is missing); the server installer does it: sudo sh install-server.sh --link"
            )
            return False
        wanted = site_block(cloud, self.config, control) if cloud is not None else ""
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
