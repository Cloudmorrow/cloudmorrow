"""A bucket on the loopback, for the backup tests: the S3 calls the server makes, answered the way a store answers them.

Objects, listing with a prefix and a delimiter, and multipart uploads, in
memory. Every request must carry a signature-version-4 header for the
access key the fake was given, with the body's SHA-256 in
`x-amz-content-sha256`, or it is 403 — which is the fake catching a
request the real store would turn away.
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit
from xml.sax.saxutils import escape


class FakeS3:
    def __init__(self, bucket: str = "test", access_key: str = "AKIAFAKE") -> None:
        self.bucket = bucket
        self.access_key = access_key
        self.objects: dict[str, bytes] = {}
        self.uploads: dict[str, dict[int, bytes]] = {}
        self.requests: list[tuple[str, str]] = []
        self.lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args) -> None:  # quiet
                pass

            def _answer(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
                self.send_response(status)
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def _error(self, status: int, code: str, message: str = "") -> None:
                body = f"<Error><Code>{code}</Code><Message>{escape(message or code)}</Message></Error>".encode()
                self._answer(status, body, {"Content-Type": "application/xml"})

            def _key(self) -> tuple[str, dict[str, list[str]]]:
                parts = urlsplit(self.path)
                path = unquote(parts.path)
                prefix = "/" + fake.bucket
                if not path.startswith(prefix):
                    self._error(404, "NoSuchBucket", "the fake has one bucket")
                    raise ConnectionError
                return path[len(prefix) :].lstrip("/"), parse_qs(parts.query, keep_blank_values=True)

            def _body(self) -> bytes:
                length = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(length) if length else b""

            def _signed(self, body: bytes) -> bool:
                auth = self.headers.get("Authorization", "")
                ok = (
                    auth.startswith(f"AWS4-HMAC-SHA256 Credential={fake.access_key}/")
                    and "/s3/aws4_request" in auth
                    and all(
                        name in auth.split("SignedHeaders=", 1)[-1].split(",")[0].split(";")
                        for name in ("host", "x-amz-content-sha256", "x-amz-date")
                    )
                    and "Signature=" in auth
                    and self.headers.get("x-amz-content-sha256") == hashlib.sha256(body).hexdigest()
                    and bool(self.headers.get("x-amz-date"))
                )
                if not ok:
                    self._error(403, "SignatureDoesNotMatch", "the fake wants a signature-version-4 header")
                return ok

            def do_GET(self) -> None:
                try:
                    key, query = self._key()
                except ConnectionError:
                    return
                if not self._signed(b""):
                    return
                fake.requests.append(("GET", key or "?" + urlsplit(self.path).query))
                if "list-type" in query:
                    return self._list(query)
                with fake.lock:
                    data = fake.objects.get(key)
                if data is None:
                    return self._error(404, "NoSuchKey", key)
                self._answer(200, data, {"Content-Type": "application/octet-stream", "ETag": '"x"'})

            def _list(self, query: dict[str, list[str]]) -> None:
                prefix = (query.get("prefix") or [""])[0]
                delimiter = (query.get("delimiter") or [""])[0]
                contents: list[str] = []
                prefixes: set[str] = set()
                with fake.lock:
                    keys = sorted(fake.objects)
                    sizes = {k: len(v) for k, v in fake.objects.items()}
                for key in keys:
                    if not key.startswith(prefix):
                        continue
                    rest = key[len(prefix) :]
                    if delimiter and delimiter in rest:
                        prefixes.add(prefix + rest.split(delimiter, 1)[0] + delimiter)
                        continue
                    contents.append(f"<Contents><Key>{escape(key)}</Key><Size>{sizes[key]}</Size></Contents>")
                common = "".join(
                    f"<CommonPrefixes><Prefix>{escape(p)}</Prefix></CommonPrefixes>" for p in sorted(prefixes)
                )
                body = (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                    f"<Name>{fake.bucket}</Name><Prefix>{escape(prefix)}</Prefix><IsTruncated>false</IsTruncated>"
                    f"{''.join(contents)}{common}</ListBucketResult>"
                ).encode()
                self._answer(200, body, {"Content-Type": "application/xml"})

            def do_PUT(self) -> None:
                try:
                    key, query = self._key()
                except ConnectionError:
                    return
                body = self._body()
                if not self._signed(body):
                    return
                fake.requests.append(("PUT", key))
                if "uploadId" in query:
                    upload = query["uploadId"][0]
                    number = int(query["partNumber"][0])
                    with fake.lock:
                        if upload not in fake.uploads:
                            return self._error(404, "NoSuchUpload")
                        fake.uploads[upload][number] = body
                    return self._answer(200, b"", {"ETag": f'"part{number}"'})
                with fake.lock:
                    fake.objects[key] = body
                self._answer(200, b"", {"ETag": '"' + hashlib.md5(body).hexdigest() + '"'})  # noqa: S324

            def do_POST(self) -> None:
                try:
                    key, query = self._key()
                except ConnectionError:
                    return
                body = self._body()
                if not self._signed(body):
                    return
                fake.requests.append(("POST", key))
                if "uploads" in query:
                    upload = uuid.uuid4().hex
                    with fake.lock:
                        fake.uploads[upload] = {}
                    xml = (
                        f"<InitiateMultipartUploadResult><Bucket>{fake.bucket}</Bucket><Key>{escape(key)}</Key>"
                        f"<UploadId>{upload}</UploadId></InitiateMultipartUploadResult>"
                    )
                    return self._answer(200, xml.encode(), {"Content-Type": "application/xml"})
                if "uploadId" in query:
                    upload = query["uploadId"][0]
                    with fake.lock:
                        parts = fake.uploads.pop(upload, None)
                        if parts is None:
                            return self._error(404, "NoSuchUpload")
                        fake.objects[key] = b"".join(parts[n] for n in sorted(parts))
                    xml = f"<CompleteMultipartUploadResult><Key>{escape(key)}</Key></CompleteMultipartUploadResult>"
                    return self._answer(200, xml.encode(), {"Content-Type": "application/xml"})
                self._error(400, "InvalidRequest")

            def do_DELETE(self) -> None:
                try:
                    key, query = self._key()
                except ConnectionError:
                    return
                if not self._signed(b""):
                    return
                fake.requests.append(("DELETE", key))
                with fake.lock:
                    if "uploadId" in query:
                        fake.uploads.pop(query["uploadId"][0], None)
                    else:
                        fake.objects.pop(key, None)
                self._answer(204)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def endpoint(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> FakeS3:
        self.thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def keys(self, prefix: str = "") -> list[str]:
        with self.lock:
            return sorted(k for k in self.objects if k.startswith(prefix))
