#!/usr/bin/env python3
"""Tag this commit as a release, and push it.

A release is a tag. The version is not written down anywhere — `pyproject.toml`
reads it back off the nearest tag — so tagging *is* the bump, and there is no
file to remember to edit and no way for the number to disagree with the history.

The rule is one bump per push: every push of new code is a release, and it
takes the next minor. `--major` takes the next major instead, and is the only
thing anyone has to decide.

    python scripts/release.py            # 0.6.0 -> v0.7.0, tagged and pushed
    python scripts/release.py --major    # 0.6.0 -> v1.0.0
    python scripts/release.py --dry-run  # say what it would do

Run it after committing and before pushing; it pushes the commits and the tag
together, so the remote never has a commit whose release does not exist yet.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
ROOT = ["git", "rev-parse", "--show-toplevel"]


def git(*args: str, check: bool = True) -> str:
    done = subprocess.run(["git", *args], capture_output=True, text=True)
    if check and done.returncode != 0:
        detail = (done.stderr or done.stdout).strip()
        sys.exit(f"git {' '.join(args)} failed:\n{detail}")
    return done.stdout.strip()


def latest() -> tuple[int, int, int]:
    """The newest release tag, or 0.0.0 when there has never been one."""
    tags = [tag for tag in git("tag", "--list", "v*").splitlines() if TAG.match(tag)]
    if not tags:
        return (0, 0, 0)
    return max(tuple(int(part) for part in TAG.match(tag).groups()) for tag in tags)


def nxt(current: tuple[int, int, int], *, major: bool) -> str:
    big, small, _ = current
    return f"v{big + 1}.0.0" if major else f"v{big}.{small + 1}.0"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--major", action="store_true", help="Take the next major.")
    parser.add_argument("--dry-run", action="store_true", help="Say it, do nothing.")
    parser.add_argument("--remote", default="origin")
    args = parser.parse_args()

    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if git("status", "--porcelain"):
        sys.exit("the working tree has changes — commit them first, then release.")

    current = latest()
    tag = nxt(current, major=args.major)
    if git("tag", "--list", tag):
        sys.exit(f"{tag} already exists.")
    # A tag on a commit that is already released says the push had nothing in
    # it, and two tags on one commit make "which release is this" ambiguous.
    here = git("tag", "--points-at", "HEAD", check=False)
    if any(TAG.match(line) for line in here.splitlines()):
        sys.exit(f"HEAD is already released as {here} — nothing new to push.")

    subject = git("log", "-1", "--pretty=%s")
    print(f"v{'.'.join(str(n) for n in current)} → {tag}   on {branch}")
    print(f"  {subject}")
    if args.dry_run:
        print("  (dry run — nothing tagged, nothing pushed)")
        return

    git("tag", "-a", tag, "-m", f"{tag}: {subject}")
    # --follow-tags pushes the commits and this tag in one go, so there is never
    # a moment where the remote has code whose release tag has not arrived.
    git("push", "--follow-tags", args.remote, branch)
    print(f"  tagged and pushed to {args.remote}/{branch}")


if __name__ == "__main__":
    main()
