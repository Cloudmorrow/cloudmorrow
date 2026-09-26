"""Relay's service: writes a ping when it starts, then answers on $PORT."""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from common import ping


class Handler(BaseHTTPRequestHandler):
    def _answer(self, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Set-Cookie", "session=stolen")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.startswith("/crash"):
            os._exit(3)
        if self.path.startswith("/env"):
            return self._answer(dict(os.environ))
        return self._answer({
            "path": self.path,
            "user": self.headers.get("X-Cloudmorrow-User"),
            "quill": self.headers.get("X-Cloudmorrow-Quill"),
            "api": self.headers.get("X-Cloudmorrow-Api"),
            "authorization": self.headers.get("Authorization"),
            "cookie": self.headers.get("Cookie"),
        })

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode()
        return self._answer({
            "path": self.path,
            "body": body,
            "webhook": self.headers.get("X-Cloudmorrow-Webhook"),
            "token": self.headers.get("X-Cloudmorrow-Webhook-Token"),
        })

    def log_message(self, *args) -> None:
        print("served", self.path, flush=True)


if __name__ == "__main__":
    ping("hello from the service", "service")
    ThreadingHTTPServer(("127.0.0.1", int(os.environ["PORT"])), Handler).serve_forever()
