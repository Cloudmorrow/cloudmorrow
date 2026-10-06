#!/usr/bin/env python3
"""Release Cloudmorrow and put the pieces we run into production.

    make deploy                     what is where, then a menu
    make deploy WHAT=status         only what is where
    make deploy WHAT=explain        how versions fit together
    make deploy WHAT=release        tag the next minor of the core: v0.14.0 -> v0.15.0
    make deploy WHAT=release BUMP=patch   (or BUMP=major)
    make deploy WHAT=website        cloudmorrow.com, from ../cloudmorrow-web
    make deploy WHAT=mail           the Worker behind certs@ and hi@cloudmorrow.com
    make deploy WHAT=all            every one of those that is behind: core, website, mail

Every step says what it will do and asks first (YES=1 to not ask). It never
touches anybody's own cloud: those update themselves, or with
`cloudmorrow update server`. See `make deploy WHAT=explain`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = Path(os.environ.get("CLOUDMORROW_WEB_DIR", ROOT.parent / "cloudmorrow-web"))
HOST = os.environ.get("CLOUDMORROW_DEPLOY_HOST", "root@178.105.27.139")
CORE_REPO = "Cloudmorrow/cloudmorrow"
ACCOUNT_ID = "ef65820d931a60652e1d853651358bac"
WORKER = "cloudmorrow-mail"
TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")

EXPLAIN = """\
How versions fit together
=========================

There is ONE version number: the core's, a git tag like v0.14.0 on
Cloudmorrow/cloudmorrow. Nothing else has a number; the rest is "which
commit is live".

  Making a version     `make deploy WHAT=release` tags the commit on main
                       and pushes it. Tagging IS the bump: pyproject.toml
                       reads the version back off the tag, there is no file
                       to edit. Minor by default (v0.14.0 -> v0.15.0);
                       BUMP=patch for a fix alone, BUMP=major for a break.

  What the tag builds  GitHub Actions (release.yml) builds that version's
                       wheel and the client installer (install.sh, pointed
                       at the wheel) and publishes them as a GitHub Release.

  Who gets it          - New computers: the client installer from
                         releases/latest.
                       - Clouds: the `cm` client and desktop app update from
                         their own cloud, which serves its own install.sh.

  Deployed by commit   These have no version; what matters is the commit:
                       - cloudmorrow.com (Cloudmorrow/cloudmorrow-web)
                       - the mail Worker (cloudmorrow-web/mail-worker)

  The one loose end    The SERVER installer (install-server.sh) and
                       `cloudmorrow update server` follow the main branch,
                       not the latest release: a server gets whatever is on
                       main when it installs or updates, tagged or not. So
                       release before you push something a server should
                       not get yet. (Tying servers to releases is a change
                       of its own; say the word.)

  Your own clouds      Never deployed from here. Update them with
                       `cloudmorrow update server` or `cloudmorrow-update`.
"""

# -- output ---------------------------------------------------------------------------
COLOUR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def paint(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if COLOUR else text


def ok(text: str) -> str:
    return paint("32", text)


def warn(text: str) -> str:
    return paint("33", text)


def bad(text: str) -> str:
    return paint("31", text)


def dim(text: str) -> str:
    return paint("2", text)


def say(text: str) -> None:
    print(paint("36", "::") + " " + text, flush=True)


# -- running things --------------------------------------------------------------------
class Failed(Exception):
    """A step that did not work, in a sentence."""


def run(cmd: list[str], *, cwd: Path | None = None, check: bool = True, timeout: int = 120) -> str:
    try:
        done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise Failed(f"{cmd[0]} is not installed") from None
    except subprocess.TimeoutExpired:
        raise Failed(f"{' '.join(cmd[:3])} took longer than {timeout}s") from None
    if check and done.returncode != 0:
        detail = (done.stderr or done.stdout).strip().splitlines()
        raise Failed(f"{' '.join(cmd[:3])} failed: {detail[-1] if detail else done.returncode}")
    return done.stdout.strip()


def live(cmd: list[str], *, cwd: Path | None = None) -> None:
    """Run with its output on the screen: the long steps, so nobody wonders."""
    print(dim("   $ " + " ".join(shlex.quote(c) for c in cmd)), flush=True)
    if subprocess.run(cmd, cwd=cwd).returncode != 0:
        raise Failed(f"{' '.join(cmd[:3])} failed (its output is above)")


def ssh(script: str, *, timeout: int = 120) -> str:
    return run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", HOST, script], timeout=timeout)


def git(*args: str, cwd: Path = ROOT, check: bool = True) -> str:
    return run(["git", *args], cwd=cwd, check=check)


def gh(*args: str) -> str:
    return run(["gh", *args], timeout=60)


def http_status(url: str) -> int:
    request = urllib.request.Request(url, headers={"User-Agent": "cloudmorrow-deploy"})
    try:
        with urllib.request.urlopen(request, timeout=20) as answer:
            return answer.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except OSError:
        return 0


def wait_for(what: str, check, seconds: int = 180) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return
        time.sleep(3)
    raise Failed(f"{what} did not happen within {seconds}s")


# -- versions ---------------------------------------------------------------------------
def parse(tag: str) -> tuple[int, int, int] | None:
    match = TAG.match(tag)
    return tuple(int(n) for n in match.groups()) if match else None  # type: ignore[return-value]


def bumped(current: tuple[int, int, int], bump: str) -> str:
    big, small, tiny = current
    return {
        "major": f"v{big + 1}.0.0",
        "minor": f"v{big}.{small + 1}.0",
        "patch": f"v{big}.{small}.{tiny + 1}",
    }[bump]


def latest_tag(cwd: Path = ROOT) -> str | None:
    tags = [t for t in git("tag", "--list", "v*", cwd=cwd).splitlines() if parse(t)]
    return max(tags, key=parse) if tags else None


# -- what is where -------------------------------------------------------------------
@dataclass
class State:
    name: str
    what: str  # one line: the version or commit that is live
    behind: bool = False  # something is waiting to go out
    notes: list[str] = field(default_factory=list)  # plain sentences, worst first
    blocked: str = ""  # why deploying now would be refused


def core_state() -> State:
    git("fetch", "--quiet", "--tags", "origin", check=False)
    tag = latest_tag()
    state = State("core", f"{tag or 'no release yet'}")
    if git("status", "--porcelain"):
        state.blocked = "the core checkout has uncommitted changes"
        state.notes.append(warn("uncommitted changes in " + str(ROOT)))
    ahead = git("rev-list", "--count", "origin/main..HEAD", check=False) or "0"
    if ahead != "0":
        state.notes.append(warn(f"{ahead} local commit(s) not pushed yet (a release pushes them)"))
    unreleased = int(git("rev-list", "--count", f"{tag}..HEAD" if tag else "HEAD") or 0)
    if unreleased:
        state.behind = True
        state.notes.append(warn(f"{unreleased} commit(s) since {tag}, not in any release"))
    else:
        state.notes.append(ok(f"everything on main is in {tag}"))
    if tag:
        try:
            assets = json.loads(gh("release", "view", tag, "-R", CORE_REPO, "--json", "assets"))["assets"]
            names = sorted(a["name"] for a in assets)
            state.notes.append(
                ok(f"GitHub Release {tag}: {', '.join(names)}") if names else bad(f"GitHub Release {tag} has no files")
            )
        except Failed:
            state.notes.append(bad(f"no GitHub Release for {tag} (did its build fail? gh run list -R {CORE_REPO})"))
    head = git("rev-parse", "HEAD")
    try:
        runs = json.loads(
            gh(
                "run",
                "list",
                "-R",
                CORE_REPO,
                "--commit",
                head,
                "--workflow",
                "ci.yml",
                "--json",
                "status,conclusion",
                "--limit",
                "1",
            )
        )
        if runs and runs[0]["status"] != "completed":
            state.notes.append(warn("CI is still running on this commit"))
        elif runs and runs[0]["conclusion"] != "success":
            state.notes.append(bad(f"CI failed on this commit ({runs[0]['conclusion']})"))
            state.blocked = state.blocked or "CI failed on this commit"
        elif not runs:
            state.notes.append(dim("CI has not run on this commit (not pushed yet?)"))
        else:
            state.notes.append(ok("CI passed on this commit"))
    except Failed as exc:
        state.notes.append(dim(f"CI unknown: {exc}"))
    return state


def website_state() -> State:
    if not (WEB / ".git").exists():
        return State("website", "?", blocked=f"no checkout at {WEB} (set CLOUDMORROW_WEB_DIR)")
    git("fetch", "--quiet", "origin", cwd=WEB, check=False)
    head = git("rev-parse", "--short", "HEAD", cwd=WEB)
    state = State("website", "?")
    try:
        deployed = ssh("cat /opt/cloudmorrow-web/src/COMMIT").strip()
        state.what = f"{deployed} live"
    except Failed as exc:
        deployed = ""
        state.notes.append(bad(f"cannot read what is live: {exc}"))
    if git("status", "--porcelain", cwd=WEB):
        state.blocked = "cloudmorrow-web has uncommitted changes"
        state.notes.append(warn("uncommitted changes in " + str(WEB)))
    if git("rev-list", "--count", "origin/main..HEAD", cwd=WEB, check=False) not in ("", "0"):
        state.blocked = state.blocked or "cloudmorrow-web has commits that are not pushed"
        state.notes.append(warn("local commits not pushed: push them first, so what is live is on GitHub"))
    if deployed and not head.startswith(deployed) and not deployed.startswith(head):
        count = git("rev-list", "--count", f"{deployed}..HEAD", cwd=WEB, check=False) or "?"
        state.behind = True
        state.notes.append(warn(f"{count} commit(s) newer than what is live ({head})"))
        for line in git("log", "--oneline", f"{deployed}..HEAD", cwd=WEB, check=False).splitlines()[:5]:
            state.notes.append(dim("   " + line))
    elif deployed:
        state.notes.append(ok("live is the latest commit"))
    code = http_status("https://cloudmorrow.com/")
    state.notes.append(ok("cloudmorrow.com answers 200") if code == 200 else bad(f"cloudmorrow.com answers {code}"))
    return state


def cloudflare_token() -> str:
    env = WEB / ".env"
    for line in env.read_text().splitlines() if env.exists() else []:
        if line.startswith("CLOUDFLARE_API_TOKEN="):
            return line.split("=", 1)[1].strip().strip("\"'")
    return os.environ.get("CLOUDFLARE_API_TOKEN", "")


def mail_state() -> State:
    state = State("mail", "?")
    changed = (
        git("log", "-1", "--format=%cI %h", "--", "mail-worker", cwd=WEB, check=False)
        if (WEB / ".git").exists()
        else ""
    )
    token = cloudflare_token()
    if not token:
        state.notes.append(bad("no CLOUDFLARE_API_TOKEN in cloudmorrow-web/.env"))
        return state
    request = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/workers/scripts/{WORKER}/deployments",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as answer:
            deployments = json.load(answer)["result"]["deployments"]
        deployed_at = deployments[0]["created_on"]
    except (OSError, KeyError, IndexError, ValueError) as exc:
        state.notes.append(bad(f"cannot ask Cloudflare: {exc}"))
        return state
    state.what = f"deployed {deployed_at[:16].replace('T', ' ')} UTC"
    if changed:
        when, sha = changed.split()
        if dt.datetime.fromisoformat(when) > dt.datetime.fromisoformat(deployed_at.replace("Z", "+00:00")):
            state.behind = True
            state.notes.append(warn(f"mail-worker/ changed after that ({sha})"))
        else:
            state.notes.append(ok("no change to mail-worker/ since"))
    return state


# In the order `all` deploys them.
COMPONENTS = {"core": core_state, "website": website_state, "mail": mail_state}
TITLES = {
    "core": "Core release (the version people download)",
    "website": "cloudmorrow.com",
    "mail": "Mail Worker (certs@, hi@)",
}


def gather() -> dict[str, State]:
    states = {}
    for key, read in COMPONENTS.items():
        try:
            states[key] = read()
        except Failed as exc:
            states[key] = State(key, "?", notes=[bad(str(exc))], blocked=str(exc))
    return states


def show(states: dict[str, State]) -> None:
    print()
    for key, state in states.items():
        mark = warn("● waiting to go out") if state.behind else ok("● up to date")
        print(f"  {paint('1', TITLES[key])}   {state.what}   {mark}")
        for note in state.notes:
            print(f"      {note}")
        if state.blocked:
            print(f"      {bad('cannot deploy now: ' + state.blocked)}")
        print()


# -- doing things ------------------------------------------------------------------------
def confirm(question: str, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        raise Failed("not asking without a terminal: run with YES=1")
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def release(bump: str, yes: bool) -> None:
    state = core_state()
    if state.blocked:
        raise Failed(state.blocked)
    if git("rev-parse", "--abbrev-ref", "HEAD") != "main":
        raise Failed("release from main: check out main first")
    tag = latest_tag()
    current = parse(tag) if tag else (0, 0, 0)
    new = bumped(current, bump)  # type: ignore[arg-type]
    if not state.behind:
        raise Failed(f"nothing to release: main is {tag}")
    print(f"\n  {tag} → {paint('1', new)}  ({bump})")
    for line in git("log", "--oneline", f"{tag}..HEAD").splitlines()[:15]:
        print(dim("    " + line))
    print("\n  This tags main as " + new + ", pushes it, and GitHub builds the wheel and")
    print("  the client installer into a Release. Servers that update get main anyway.")
    if not confirm(f"Release {new}?", yes):
        return
    flag = {"major": ["--major"], "patch": ["--patch"], "minor": []}[bump]
    live([sys.executable, str(ROOT / "scripts" / "release.py"), *flag], cwd=ROOT)
    say(f"waiting for GitHub to build {new}")

    def run_done() -> bool:
        runs = json.loads(
            gh(
                "run",
                "list",
                "-R",
                CORE_REPO,
                "--workflow",
                "release.yml",
                "--branch",
                new,
                "--json",
                "status,conclusion",
                "--limit",
                "1",
            )
        )
        if runs and runs[0]["status"] == "completed":
            if runs[0]["conclusion"] != "success":
                raise Failed(f"the release build failed: gh run list -R {CORE_REPO} --workflow release.yml")
            return True
        return False

    wait_for(f"the release build for {new}", run_done, 900)
    assets = json.loads(gh("release", "view", new, "-R", CORE_REPO, "--json", "assets"))["assets"]
    say(ok(f"{new} is released: {', '.join(sorted(a['name'] for a in assets))}"))
    code = http_status(f"https://github.com/{CORE_REPO}/releases/latest/download/install.sh")
    say(
        ok("the landing pages' installer link works")
        if code == 200
        else bad(f"releases/latest/download/install.sh answers {code}")
    )


def website(yes: bool) -> None:
    state = website_state()
    if state.blocked:
        raise Failed(state.blocked)
    if not state.behind and not confirm("The website is up to date. Deploy it again anyway?", yes):
        return
    head = git("log", "-1", "--format=%h %s", cwd=WEB)
    print(f"\n  cloudmorrow.com: {state.what} → {paint('1', head)}")
    print("  Backs up the site's database on the box, then sends the commit and restarts.")
    if not confirm("Deploy the website?", yes):
        return
    stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M")
    ssh(
        "cd /var/lib/cloudmorrow-web && "
        f"(sqlite3 site.db '.backup site.db.pre-deploy-{stamp}' 2>/dev/null"
        f" || cp -a site.db site.db.pre-deploy-{stamp}) && "
        f"chmod 600 site.db.pre-deploy-{stamp}"
    )
    say(f"database backed up as /var/lib/cloudmorrow-web/site.db.pre-deploy-{stamp}")
    live(["sh", "deploy/deploy.sh"], cwd=WEB)
    wait_for("cloudmorrow.com to answer", lambda: http_status("https://cloudmorrow.com/") == 200, 60)
    say(ok("cloudmorrow.com is live on " + head))


def mail(yes: bool) -> None:
    state = mail_state()
    if not state.behind and not confirm("The mail Worker is up to date. Deploy it again anyway?", yes):
        return
    print("\n  Runs cloudmorrow-web/deploy/mail-worker.sh: tests, deploys the Worker,")
    print("  sets its secret and the routing for certs@ and hi@.")
    if not confirm("Deploy the mail Worker?", yes):
        return
    live(["sh", "deploy/mail-worker.sh"], cwd=WEB)
    say(ok("the mail Worker is deployed"))


def everything(bump: str, yes: bool) -> None:
    states = gather()
    show(states)
    waiting = [k for k, s in states.items() if s.behind]
    if not waiting:
        say(ok("everything is up to date"))
        return
    blocked = [f"{k}: {states[k].blocked}" for k in waiting if states[k].blocked]
    if blocked:
        raise Failed("fix these first: " + "; ".join(blocked))
    say("in order: " + ", ".join(waiting))
    steps = {
        "core": lambda: release(bump, yes),
        "website": lambda: website(yes),
        "mail": lambda: mail(yes),
    }
    for key in waiting:
        steps[key]()


def menu(bump: str, yes: bool) -> None:
    states = gather()
    show(states)
    choices = [
        ("release", f"Release the core ({bump}: {bumped(parse(latest_tag() or 'v0.0.0'), bump)})"),  # type: ignore[arg-type]
        ("website", "Deploy cloudmorrow.com"),
        ("mail", "Deploy the mail Worker"),
        ("all", "Everything that is waiting, in order"),
        ("explain", "How versions fit together"),
    ]
    for number, (_, text) in enumerate(choices, 1):
        print(f"  {number}. {text}")
    if not sys.stdin.isatty():
        return
    picked = input("\nWhich? (Enter to stop) ").strip()
    if not picked.isdigit() or not 1 <= int(picked) <= len(choices):
        return
    act(choices[int(picked) - 1][0], bump, yes)


def act(what: str, bump: str, yes: bool) -> None:
    if what == "status":
        show(gather())
    elif what == "explain":
        print(EXPLAIN)
    elif what == "release":
        release(bump, yes)
    elif what == "website":
        website(yes)
    elif what == "mail":
        mail(yes)
    elif what == "all":
        everything(bump, yes)
    else:
        raise Failed(f"unknown: {what} (status, explain, release, website, mail, all)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("what", nargs="?", default="", help="status, explain, release, website, mail or all")
    parser.add_argument("--bump", choices=("minor", "major", "patch"), default="minor")
    parser.add_argument("--yes", action="store_true", help="do not ask")
    args = parser.parse_args()
    try:
        if args.what:
            act(args.what, args.bump, args.yes)
        else:
            menu(args.bump, args.yes)
    except Failed as exc:
        print(bad(f"stopped: {exc}"), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print()
        sys.exit(130)


if __name__ == "__main__":
    main()
