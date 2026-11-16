"""Tell the world about a release, without anybody at a keyboard.

Run by .github/workflows/announce.yml when a GitHub Release is published.
It writes one short post, the tag's subject and the release's address, and
sends it to every place it has a key for; a place with no key is skipped
and said so, never an error. The keys are repository secrets:

    MASTODON_URL       https://fosstodon.org (the instance)
    MASTODON_TOKEN     an access token with write:statuses
    BLUESKY_HANDLE     cloudmorrow.bsky.social (or the domain handle)
    BLUESKY_PASSWORD   an app password, never the account's

    python scripts/announce.py v0.94.0 "v0.94.0: the subject" https://github.com/.../releases/tag/v0.94.0
    python scripts/announce.py --dry-run ...     prints the post, sends nothing
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

TIMEOUT = 20


def post_text(tag: str, subject: str, url: str) -> str:
    """'Cloudmorrow v0.94.0: the subject', then the address. Short on purpose."""
    words = subject.split(":", 1)[1].strip() if subject.startswith(tag) and ":" in subject else subject
    words = words[0].upper() + words[1:] if words else "a new release"
    return f"Cloudmorrow {tag}: {words}\n\n{url}"


def _json(req: urllib.request.Request) -> dict:
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def mastodon(text: str, env: dict[str, str]) -> str:
    base, token = env.get("MASTODON_URL", "").rstrip("/"), env.get("MASTODON_TOKEN", "")
    if not base or not token:
        return "mastodon: no key, skipped"
    data = json.dumps({"status": text, "visibility": "public", "language": "en"}).encode()
    req = urllib.request.Request(
        f"{base}/api/v1/statuses",
        data=data,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Idempotency-Key": text[:64]},
    )
    return "mastodon: " + _json(req).get("url", "posted")


def bluesky_facets(text: str) -> list[dict]:
    """A link facet for each https address, by UTF-8 byte offsets, as Bluesky wants."""
    facets = []
    raw = text.encode("utf-8")
    start = 0
    while (i := raw.find(b"https://", start)) != -1:
        j = i
        while j < len(raw) and raw[j] not in b" \n\t":
            j += 1
        facets.append(
            {
                "index": {"byteStart": i, "byteEnd": j},
                "features": [{"$type": "app.bsky.richtext.facet#link", "uri": raw[i:j].decode()}],
            }
        )
        start = j
    return facets


def bluesky(text: str, env: dict[str, str]) -> str:
    handle, password = env.get("BLUESKY_HANDLE", ""), env.get("BLUESKY_PASSWORD", "")
    if not handle or not password:
        return "bluesky: no key, skipped"
    base = "https://bsky.social/xrpc"
    session = _json(
        urllib.request.Request(
            f"{base}/com.atproto.server.createSession",
            method="POST",
            data=json.dumps({"identifier": handle, "password": password}).encode(),
            headers={"Content-Type": "application/json"},
        )
    )
    from datetime import UTC, datetime

    record = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "facets": bluesky_facets(text),
        "langs": ["en"],
        "createdAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    made = _json(
        urllib.request.Request(
            f"{base}/com.atproto.repo.createRecord",
            method="POST",
            data=json.dumps({"repo": session["did"], "collection": "app.bsky.feed.post", "record": record}).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {session['accessJwt']}"},
        )
    )
    return "bluesky: " + made.get("uri", "posted")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("tag")
    parser.add_argument("subject")
    parser.add_argument("url")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    text = post_text(args.tag, args.subject, args.url)
    print(text)
    if args.dry_run:
        return 0
    failed = False
    for place in (mastodon, bluesky):
        try:
            print(place(text, dict(os.environ)))
        except urllib.error.HTTPError as e:
            print(f"{place.__name__}: HTTP {e.code} {e.read()[:200]!r}", file=sys.stderr)
            failed = True
        except Exception as e:  # noqa: BLE001 - one place failing must not stop the next
            print(f"{place.__name__}: {e}", file=sys.stderr)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
