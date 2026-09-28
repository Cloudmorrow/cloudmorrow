"""The sandbox's side of the conversation: JSON lines over standard in and out.

The interpreter starts, loads the Quill, says what it found, and then runs
one call at a time for as long as the host keeps it:

    host  -> {"t": "call", "kind": "action", "name": "log_service", "ctx": {...}, "args": {...}}
    guest -> {"t": "host", "op": "records.get", "args": {...}}      as often as the handler asks
    host  -> {"t": "reply", "ok": true, "value": ...}
    guest -> {"t": "done", "value": ...}   or   {"t": "fail", "kind": ..., "message": ..., "trace": ...}

Standard out is the conversation, so what a handler prints is caught and
sent as `ctx.log` lines instead of reaching it.
"""

from __future__ import annotations

import io
import json
import sys

from cloudmorrow.quill import dispatch
from cloudmorrow.quill.context import ERRORS, Invalid


class _Log(io.TextIOBase):
    """print() in a handler: a log line, not a broken conversation."""

    def __init__(self, send) -> None:
        self._send = send
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._send({"t": "log", "line": line})
        return len(text)


def main(folder: str = "/quill", code: str = "quill.py") -> None:
    out = sys.stdout
    reader = sys.stdin

    def send(message: dict) -> None:
        out.write(json.dumps(message, separators=(",", ":")) + "\n")
        out.flush()

    def receive() -> dict | None:
        line = reader.readline()
        if not line:
            return None
        return json.loads(line)

    sys.stdout = _Log(send)

    def host(op: str, args: dict):
        if op == "log":
            send({"t": "log", "line": str(args.get("line", ""))})
            return None
        send({"t": "host", "op": op, "args": args})
        reply = receive()
        if reply is None:
            raise SystemExit(0)
        if reply.get("ok"):
            return reply.get("value")
        raise ERRORS.get(reply.get("kind", ""), Invalid)(reply.get("message", "refused"))

    try:
        handlers = dispatch.load(folder, code)
    except Exception as exc:  # the Quill does not import: say so, and wait to be stopped
        send({"t": "broken", "message": f"{type(exc).__name__}: {exc}", "trace": dispatch._trace(exc)})
        return
    send({"t": "ready", "handlers": handlers})

    while True:
        message = receive()
        if message is None:
            return
        if message.get("t") != "call":
            continue
        try:
            value = dispatch.call(
                message["kind"], message["name"], message.get("ctx", {}), message.get("args", {}), host
            )
        except dispatch.Failure as failure:
            send({"t": "fail", **failure.to_dict()})
            continue
        try:
            send({"t": "done", "value": value})
        except (TypeError, ValueError) as exc:
            send({"t": "fail", "kind": "error", "message": f"the result is not JSON: {exc}", "trace": ""})


if __name__ == "__main__":
    main(*sys.argv[1:3])
