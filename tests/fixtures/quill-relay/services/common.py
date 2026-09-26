"""What both of Relay's programs do: write a ping through the record API."""

import json
import os
import time
import urllib.request


def ping(text: str, source: str) -> None:
    """One relay.ping record, as the Quill, retried while the server comes up."""
    body = json.dumps({"fields": {"text": text, "source": source}}).encode()
    request = urllib.request.Request(
        os.environ["CLOUDMORROW_URL"] + "/api/records/relay.ping",
        data=body,
        method="POST",
        headers={
            "Authorization": "Bearer " + os.environ["CLOUDMORROW_TOKEN"],
            "Content-Type": "application/json",
        },
    )
    for _ in range(50):
        try:
            with urllib.request.urlopen(request, timeout=5) as answer:
                print("wrote", json.loads(answer.read())["id"], flush=True)
                return
        except OSError as exc:
            print("not yet:", exc, flush=True)
            time.sleep(0.1)
