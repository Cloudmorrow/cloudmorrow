"""Local backups, on the machine: the folders the person set up, copied
into their My Files and kept up to date.

Each tick the agent asks the server which of its folders to back up and
runs the ones that are due: it walks the folder, asks what the drive holds
under the backup's place, sends what is new or changed (by size and the
moment it changed), takes away what is gone (to the drive's Trash), and
says how it went. A folder outside this machine's `backup_roots` is
refused, like a backup job would be; hidden files and links are passed
over; a file that cannot be read is said and skipped.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from cloudmorrow.agent.client import AgentApiError, AgentClient
from cloudmorrow.agent.config import AgentConfig
from cloudmorrow.agent.tasks import TaskRefused, _resolve_under

log = logging.getLogger("cloudmorrow.agent")

# A file this big or bigger is not sent: a backup is of documents and
# photos, not of disk images.
MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024


def _walk(top: Path) -> dict[str, Path]:
    """Every file under *top*, by its path relative to it; hidden ones and links passed over."""
    found: dict[str, Path] = {}
    for root, dirs, files in os.walk(top):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (Path(root) / d).is_symlink())
        for name in sorted(files):
            target = Path(root) / name
            if name.startswith(".") or target.is_symlink():
                continue
            found[str(target.relative_to(top)).replace(os.sep, "/")] = target
    return found


class LocalSyncs:
    def __init__(self, config: AgentConfig, client: AgentClient) -> None:
        self.config = config
        self.client = client

    def tick(self) -> list[int]:
        """Run every backup that is due. Returns the ids run."""
        if not self.config.allow_backup:
            return []
        ran = []
        for sync in self.client.syncs():
            if not self._due(sync):
                continue
            self.run(sync)
            ran.append(int(sync["id"]))
        return ran

    @staticmethod
    def _due(sync: dict) -> bool:
        import datetime as dt

        if sync.get("run_now") or not sync.get("last_run"):
            return True
        last = dt.datetime.fromisoformat(sync["last_run"])
        return dt.datetime.now(tz=dt.UTC) - last >= dt.timedelta(minutes=int(sync.get("every_minutes") or 60))

    def run(self, sync: dict) -> dict:
        """One pass over one folder, and the word to the server on how it went."""
        sync_id = int(sync["id"])
        try:
            result = self._pass(sync_id, str(sync["path"]))
        except TaskRefused as exc:
            result = {"ok": False, "said": str(exc)}
        except AgentApiError:
            raise
        except OSError as exc:
            result = {"ok": False, "said": f"{exc.strerror or exc}"}
        except Exception as exc:  # a bug here must not stop the agent
            log.exception("backup %s crashed", sync_id)
            result = {"ok": False, "said": f"agent error: {exc}"}
        self.client.sync_done(sync_id, result)
        return result

    def _pass(self, sync_id: int, raw_path: str) -> dict:
        top = _resolve_under(raw_path, self.config.backup_roots)
        if not top.is_dir():
            raise TaskRefused(f"there is no folder at {top}")
        local = _walk(top)
        remote = self.client.sync_files(sync_id)
        sent = 0
        size = 0
        skipped: list[str] = []
        for rel, target in local.items():
            try:
                stat = target.stat()
            except OSError:
                skipped.append(rel)
                continue
            if stat.st_size >= MAX_FILE_BYTES:
                skipped.append(rel)
                continue
            there = remote.get(rel)
            if (
                there
                and int(there.get("size", -1)) == stat.st_size
                and abs(float(there.get("modified", 0)) - stat.st_mtime) < 2
            ):
                continue
            try:
                self.client.sync_put(sync_id, rel, target, stat.st_mtime)
            except OSError:
                skipped.append(rel)
                continue
            sent += 1
            size += stat.st_size
        removed = 0
        for rel in remote:
            if rel not in local:
                self.client.sync_remove(sync_id, rel)
                removed += 1
        said = f"{sent} sent, {removed} taken away"
        if skipped:
            said += f"; {len(skipped)} could not be read: {', '.join(skipped[:3])}"
        return {"ok": True, "said": said, "files": len(local), "bytes": size}
