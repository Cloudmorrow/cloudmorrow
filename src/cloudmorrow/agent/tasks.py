"""What the agent can actually do.

Every task is a plain function of (payload, config) -> result dict. They raise
TaskError for anything the operator should see as a failed job rather than a
crashed agent.
"""

from __future__ import annotations

import datetime as dt
import os
import platform
import shutil
import socket
import subprocess
import tarfile
import time
from pathlib import Path

from cloudmorrow import __version__
from cloudmorrow.agent.config import AgentConfig

MAX_OUTPUT_CHARS = 8000


class TaskError(RuntimeError):
    """The job failed, and this is why."""


class TaskRefused(TaskError):
    """The job asked for something this machine is not configured to allow."""


def _resolve_under(path_str: str, roots: list[str]) -> Path:
    """Resolve *path_str*, insisting it sits under one of the allowed roots."""
    path = Path(path_str).expanduser().resolve()
    for root in roots:
        root_path = Path(root).expanduser().resolve()
        if path == root_path or root_path in path.parents:
            return path
    raise TaskRefused(f"{path} is outside this agent's allowed roots ({', '.join(roots)})")


def task_ping(payload: dict, config: AgentConfig) -> dict:
    return {
        "pong": True,
        "agent": config.name,
        "version": __version__,
        "echo": payload.get("echo", ""),
        "time": dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds"),
    }


def task_sysinfo(payload: dict, config: AgentConfig) -> dict:
    paths = payload.get("paths") or ["/"]
    disks = {}
    for raw in paths:
        try:
            usage = shutil.disk_usage(raw)
        except OSError as exc:
            disks[raw] = {"error": str(exc)}
            continue
        disks[raw] = {
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "percent_used": round(usage.used / usage.total * 100, 1) if usage.total else 0.0,
        }
    info = {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "agent_version": __version__,
        "cpus": os.cpu_count(),
        "disks": disks,
    }
    if hasattr(os, "getloadavg"):
        info["load_average"] = [round(value, 2) for value in os.getloadavg()]
    return info


def task_backup(payload: dict, config: AgentConfig) -> dict:
    """tar.gz one or more paths into the agent's backup directory."""
    if not config.allow_backup:
        raise TaskRefused("backups are disabled on this agent")
    raw_paths = payload.get("paths") or []
    if not raw_paths:
        raise TaskError("backup needs at least one path")

    sources = [_resolve_under(raw, config.backup_roots) for raw in raw_paths]
    missing = [str(path) for path in sources if not path.exists()]
    if missing:
        raise TaskError(f"no such path: {', '.join(missing)}")

    destination = Path(payload.get("destination") or config.backup_dir).expanduser()
    destination.mkdir(parents=True, exist_ok=True)
    label = str(payload.get("name") or "backup").replace("/", "-")
    stamp = dt.datetime.now(tz=dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    archive = destination / f"{label}-{stamp}.tar.gz"
    excludes = {str(pattern) for pattern in payload.get("exclude") or []}

    started = time.monotonic()
    file_count = 0

    def keep(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        nonlocal file_count
        if any(pattern in info.name for pattern in excludes):
            return None
        if info.isfile():
            file_count += 1
        return info

    try:
        with tarfile.open(archive, "w:gz") as tar:
            for source in sources:
                tar.add(source, arcname=source.name, filter=keep)
    except (OSError, tarfile.TarError) as exc:
        archive.unlink(missing_ok=True)
        raise TaskError(f"backup failed: {exc}") from exc

    retention = int(payload.get("retention") or config.backup_retention)
    pruned = _prune(destination, label, retention)
    return {
        "archive": str(archive),
        "bytes": archive.stat().st_size,
        "files": file_count,
        "sources": [str(path) for path in sources],
        "pruned": pruned,
        "seconds": round(time.monotonic() - started, 2),
    }


def _prune(destination: Path, label: str, retention: int) -> list[str]:
    """Keep the newest *retention* archives for this label, delete the rest."""
    if retention <= 0:
        return []
    archives = sorted(
        destination.glob(f"{label}-*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    removed = []
    for old in archives[retention:]:
        old.unlink(missing_ok=True)
        removed.append(str(old))
    return removed


def task_shell(payload: dict, config: AgentConfig) -> dict:
    """Run a command. Off unless this machine's config enables it."""
    if not config.allow_shell:
        raise TaskRefused("shell jobs are disabled on this agent (allow_shell = false)")
    command = payload.get("command")
    if not command:
        raise TaskError("shell needs a command")
    timeout = int(payload.get("timeout") or config.shell_timeout_seconds)
    cwd = payload.get("cwd")
    try:
        completed = subprocess.run(  # noqa: S602 - running commands is the point
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TaskError(f"command timed out after {timeout}s") from exc
    except OSError as exc:
        raise TaskError(f"could not run command: {exc}") from exc
    result = {
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout[:MAX_OUTPUT_CHARS],
        "stderr": completed.stderr[:MAX_OUTPUT_CHARS],
        "truncated": len(completed.stdout) > MAX_OUTPUT_CHARS
        or len(completed.stderr) > MAX_OUTPUT_CHARS,
    }
    if completed.returncode != 0:
        raise TaskError(f"command exited {completed.returncode}: {completed.stderr[:400]}")
    return result


TASKS = {
    "ping": task_ping,
    "sysinfo": task_sysinfo,
    "backup": task_backup,
    "shell": task_shell,
}


def run_task(job_type: str, payload: dict, config: AgentConfig) -> dict:
    handler = TASKS.get(job_type)
    if handler is None:
        raise TaskRefused(f"this agent does not know how to {job_type}")
    return handler(payload or {}, config)
