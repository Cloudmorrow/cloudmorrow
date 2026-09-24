"""The agent loop: heartbeat, claim a job, run it, report back."""

from __future__ import annotations

import logging
import platform
import signal
import socket
import time
from dataclasses import dataclass

from cloudmorrow.agent.client import AgentApiError, AgentClient
from cloudmorrow.agent.config import AgentConfig
from cloudmorrow.agent.shares import ShareHost
from cloudmorrow.agent.sync import sync_all
from cloudmorrow.agent.tasks import TaskError, run_task

log = logging.getLogger("cloudmorrow.agent")

# Back off when the server is unreachable, up to this many seconds.
MAX_BACKOFF_SECONDS = 300


@dataclass
class RunnerStats:
    jobs_done: int = 0
    jobs_failed: int = 0
    heartbeats: int = 0
    # Passes over a config bundle that actually moved something.
    config_syncs: int = 0


class AgentRunner:
    def __init__(self, config: AgentConfig, client: AgentClient | None = None) -> None:
        self.config = config
        self.client = client or AgentClient(config)
        self.stats = RunnerStats()
        self._stop = False
        # This machine's shares, served while the server lists any.
        self.shares = ShareHost(config, self.client)

    def stop(self, *_: object) -> None:
        log.info("stopping after the current job")
        self._stop = True

    def install_signal_handlers(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self.stop)

    # -- one pass ----------------------------------------------------------
    def run_one_job(self) -> bool:
        """Claim and run a single job. Returns True when there was one."""
        job = self.client.claim_job()
        if not job:
            return False
        job_id = job["id"]
        log.info("job %s: %s", job_id, job["type"])
        try:
            result = run_task(job["type"], job.get("payload") or {}, self.config)
        except TaskError as exc:
            self.stats.jobs_failed += 1
            log.warning("job %s failed: %s", job_id, exc)
            self.client.report(job_id, "failed", {"error": str(exc)})
            return True
        except Exception as exc:  # a bug in a task must not kill the agent
            self.stats.jobs_failed += 1
            log.exception("job %s crashed", job_id)
            self.client.report(job_id, "failed", {"error": f"agent error: {exc}"})
            return True
        self.stats.jobs_done += 1
        self.client.report(job_id, "done", result)
        return True

    def tick(self) -> None:
        """One heartbeat, the config, the shares, then drain whatever work is waiting."""
        beat = self.client.heartbeat(
            socket.gethostname(), platform.platform(), dav_base=self.shares.base_url
        )
        self.stats.heartbeats += 1
        self.sync_config(beat.get("sync_bundles") or [])
        self.serve_shares(beat.get("shares") or [])
        while not self._stop and self.run_one_job():
            pass

    def serve_shares(self, shares: list[dict]) -> None:
        """Serve whatever the server says is shared from this machine.

        Like the bundles, the list rides on the heartbeat: a share made in
        the TUI is served within one poll. Serving starts with the first
        share and stops with the last, so an idle agent holds no port.
        """
        if shares and "shares" not in self.config.capabilities:
            return
        self.shares.update(shares)

    def sync_config(self, bundles: list[str]) -> None:
        """Keep whatever the server says this machine syncs in step.

        The list comes back on the heartbeat, so switching sync on for a
        machine takes effect within one poll and needs nothing restarted.
        """
        if not bundles:
            return
        for outcome in sync_all(self.client, self.config, bundles):
            if outcome.notable:
                self.stats.config_syncs += 1
                log.info("config %s", outcome)

    # -- the loop ----------------------------------------------------------
    def run_forever(self, *, max_ticks: int | None = None) -> RunnerStats:
        if not self.config.agent_token:
            raise RuntimeError("this agent is not enrolled — run `cloudmorrow-agent enroll`")
        ticks = 0
        backoff = 0
        log.info(
            "agent %s reporting to %s (capabilities: %s)",
            self.config.name,
            self.config.server_url,
            ", ".join(self.config.capabilities),
        )
        while not self._stop and (max_ticks is None or ticks < max_ticks):
            try:
                self.tick()
                backoff = 0
            except AgentApiError as exc:
                backoff = min(MAX_BACKOFF_SECONDS, max(self.config.poll_seconds, backoff * 2 or 5))
                log.warning("server unreachable (%s); retrying in %ss", exc, backoff)
            ticks += 1
            if self._stop or (max_ticks is not None and ticks >= max_ticks):
                break
            time.sleep(backoff or self.config.poll_seconds)
        self.shares.stop()
        return self.stats
