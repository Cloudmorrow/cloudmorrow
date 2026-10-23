"""An S3 bucket, spoken plainly: the handful of calls a backup needs.

Amazon's own, and everything that speaks its protocol — Hetzner, Backblaze,
Cloudflare R2, MinIO on a box of your own, Wasabi, Scaleway. Signature
version 4 over plain HTTP(S) from the standard library: no SDK, because a
server backs up with five calls and should not carry a hundred modules to
make them. What is here: put an object, get one, delete one, list a
prefix, and the multipart dance that lets an archive of any size go up as
it is written (`Uploader`), with no copy on disk first.

Addressing: a bucket at Amazon is spoken to by its own host name
(`bucket.s3.region.amazonaws.com`); everybody else, by the path
(`endpoint/bucket/key`), which every S3-compatible store takes. The
region is part of the signature and nothing else: `us-east-1` is what a
store that does not care expects, and Amazon's is read from its host.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import io
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass, field
from urllib.parse import quote, urlsplit

__all__ = ["Bucket", "Listed", "S3Error", "Uploader", "PART_SIZE"]

# Multipart parts are at least 5 MiB and at most 10,000 of them: 64 MiB a
# part carries an object of 640 GiB, which is more drive than a home server
# has, for 64 MiB of memory while it goes up.
PART_SIZE = 64 * 1024 * 1024
# What one request may wait on the store, in seconds. Parts are large, so generous.
TIMEOUT = 300.0
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
_AMAZON_REGION = re.compile(r"s3[.-](?:dualstack\.)?([a-z]{2}-[a-z]+-\d)\.amazonaws\.com$")
_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"


class S3Error(RuntimeError):
    """The store said no, or could not be reached. `status` is 0 when it was not reached."""

    def __init__(self, message: str, *, status: int = 0, code: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass(slots=True)
class Listed:
    """One listing page: the keys under a prefix, and the folders directly under it."""

    keys: list[tuple[str, int]] = field(default_factory=list)
    prefixes: list[str] = field(default_factory=list)


def region_of(endpoint: str, given: str = "") -> str:
    """The region to sign for: what was given, else Amazon's from its host, else us-east-1."""
    if given.strip():
        return given.strip()
    found = _AMAZON_REGION.search(urlsplit(endpoint).hostname or "")
    return found.group(1) if found else "us-east-1"


def _encode_key(key: str) -> str:
    """A key as it goes in the path, encoded the way S3 signs it: every byte
    but the unreserved ones and the slashes between segments."""
    return quote(key, safe="/-_.~")


class Bucket:
    """One bucket, reached with one pair of credentials."""

    def __init__(self, endpoint: str, bucket: str, access_key: str, secret_key: str, *, region: str = "") -> None:
        parts = urlsplit(endpoint.strip())
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise S3Error(
                f"the endpoint is a URL, https://s3.eu-north-1.amazonaws.com or your provider's; not {endpoint!r}"
            )
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket.strip()):
            raise S3Error(f"not a bucket name: {bucket!r}")
        self.scheme = parts.scheme
        self.bucket = bucket.strip()
        self.region = region_of(endpoint, region)
        self.access_key = access_key.strip()
        self.secret_key = secret_key
        host = parts.hostname + (f":{parts.port}" if parts.port else "")
        # Amazon's buckets answer at their own host; everybody else by path.
        # A bucket with a dot in its name cannot be a host under TLS.
        amazon = host.endswith("amazonaws.com") and not parts.path.strip("/")
        if amazon and "." not in self.bucket:
            self.host = f"{self.bucket}.{host}"
            self.base_path = ""
        else:
            self.host = host
            self.base_path = parts.path.rstrip("/") + "/" + self.bucket

    def __repr__(self) -> str:
        return f"Bucket({self.scheme}://{self.host}{self.base_path})"

    # -- signing -------------------------------------------------------------------
    def _sign(
        self, method: str, path: str, query: list[tuple[str, str]], headers: dict[str, str], payload_hash: str
    ) -> None:
        now = dt.datetime.now(tz=dt.UTC)
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        day = now.strftime("%Y%m%d")
        headers["host"] = self.host
        headers["x-amz-date"] = stamp
        headers["x-amz-content-sha256"] = payload_hash
        canonical_query = "&".join(f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in sorted(query))
        signed = sorted(k.lower() for k in headers)
        canonical_headers = "".join(f"{k}:{' '.join(headers[k].split())}\n" for k in signed)
        request = "\n".join([method, path, canonical_query, canonical_headers, ";".join(signed), payload_hash])
        scope = f"{day}/{self.region}/s3/aws4_request"
        to_sign = "\n".join(["AWS4-HMAC-SHA256", stamp, scope, hashlib.sha256(request.encode()).hexdigest()])
        key = f"AWS4{self.secret_key}".encode()
        for piece in (day, self.region, "s3", "aws4_request"):
            key = hmac.new(key, piece.encode(), hashlib.sha256).digest()
        signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
        headers["authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={self.access_key}/{scope}, "
            f"SignedHeaders={';'.join(signed)}, Signature={signature}"
        )

    def _call(
        self,
        method: str,
        key: str = "",
        *,
        query: list[tuple[str, str]] | None = None,
        body: bytes = b"",
        content_type: str = "",
        stream: bool = False,
    ):
        path = self.base_path + "/" + _encode_key(key) if key else (self.base_path or "") + "/"
        query = list(query or [])
        headers: dict[str, str] = {}
        if content_type:
            headers["content-type"] = content_type
        self._sign(method, path, query, headers, hashlib.sha256(body).hexdigest() if body else EMPTY_SHA256)
        url = f"{self.scheme}://{self.host}{path}"
        if query:
            url += "?" + "&".join(f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in query)
        request = urllib.request.Request(url, data=body or None, method=method, headers=headers)
        try:
            response = urllib.request.urlopen(request, timeout=TIMEOUT)  # noqa: S310 - the admin's own endpoint
        except urllib.error.HTTPError as exc:
            raise self._refused(exc) from None
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            raise S3Error(f"could not reach {self.host}: {reason}") from exc
        if stream:
            return response
        with response:
            return response.read(), dict(response.headers)

    def _refused(self, exc: urllib.error.HTTPError) -> S3Error:
        code = message = ""
        try:
            root = ET.fromstring(exc.read())
            code = (root.findtext("Code") or root.findtext(f"{_NS}Code") or "").strip()
            message = (root.findtext("Message") or root.findtext(f"{_NS}Message") or "").strip()
        except (ET.ParseError, ValueError, OSError):
            pass
        said = {
            "NoSuchBucket": f"there is no bucket called {self.bucket} at {self.host}",
            "InvalidAccessKeyId": "the store does not know this access key",
            "SignatureDoesNotMatch": "the store turned the secret key away: is it right, and is the region?",
            "AccessDenied": "the store said access denied: the key may not read or write this bucket",
            "AuthorizationHeaderMalformed": "the region is wrong for this bucket" + (f": {message}" if message else ""),
            "NoSuchKey": "no such object",
        }.get(code)
        if said is None:
            said = (
                f"{self.host} answered {exc.code}" + (f" {code}" if code else "") + (f": {message}" if message else "")
            )
        return S3Error(said, status=exc.code, code=code)

    # -- objects -----------------------------------------------------------------------
    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self._call("PUT", key, body=data, content_type=content_type)

    def get(self, key: str) -> bytes:
        data, _ = self._call("GET", key)
        return data

    def open(self, key: str):
        """The object's body as a file to read from, for one too large to hold."""
        return self._call("GET", key, stream=True)

    def delete(self, key: str) -> None:
        self._call("DELETE", key)

    def list(self, prefix: str = "", *, delimiter: str = "", limit: int = 1000) -> Listed:
        """Every key under *prefix*, or with a delimiter the keys and folders directly under it."""
        found = Listed()
        token = ""
        while True:
            query = [("list-type", "2"), ("prefix", prefix), ("max-keys", str(min(limit, 1000)))]
            if delimiter:
                query.append(("delimiter", delimiter))
            if token:
                query.append(("continuation-token", token))
            data, _ = self._call("GET", query=query)
            try:
                root = ET.fromstring(data)
            except ET.ParseError as exc:
                raise S3Error(f"{self.host} did not answer a listing: {exc}") from exc
            ns = _NS if root.tag.startswith(_NS) else ""
            for item in root.iter(f"{ns}Contents"):
                found.keys.append((item.findtext(f"{ns}Key") or "", int(item.findtext(f"{ns}Size") or 0)))
            for item in root.iter(f"{ns}CommonPrefixes"):
                found.prefixes.append(item.findtext(f"{ns}Prefix") or "")
            token = root.findtext(f"{ns}NextContinuationToken") or ""
            if not token or (root.findtext(f"{ns}IsTruncated") or "").lower() != "true":
                return found
            if len(found.keys) + len(found.prefixes) >= limit:
                return found

    def delete_prefix(self, prefix: str) -> int:
        """Every object under *prefix*, gone. Answers how many."""
        gone = 0
        for key, _ in self.list(prefix, limit=100000).keys:
            self.delete(key)
            gone += 1
        return gone

    # -- multipart -----------------------------------------------------------------------
    def begin_upload(self, key: str, content_type: str = "application/octet-stream") -> str:
        data, _ = self._call("POST", key, query=[("uploads", "")], content_type=content_type)
        root = ET.fromstring(data)
        ns = _NS if root.tag.startswith(_NS) else ""
        upload_id = root.findtext(f"{ns}UploadId") or ""
        if not upload_id:
            raise S3Error(f"{self.host} began no upload for {key}")
        return upload_id

    def upload_part(self, key: str, upload_id: str, number: int, data: bytes) -> str:
        _, headers = self._call("PUT", key, query=[("partNumber", str(number)), ("uploadId", upload_id)], body=data)
        etag = {k.lower(): v for k, v in headers.items()}.get("etag", "")
        if not etag:
            raise S3Error(f"{self.host} gave part {number} of {key} no ETag")
        return etag

    def complete_upload(self, key: str, upload_id: str, etags: list[str]) -> None:
        parts = "".join(
            f"<Part><PartNumber>{n}</PartNumber><ETag>{etag}</ETag></Part>" for n, etag in enumerate(etags, 1)
        )
        body = f"<CompleteMultipartUpload>{parts}</CompleteMultipartUpload>".encode()
        data, _ = self._call("POST", key, query=[("uploadId", upload_id)], body=body, content_type="application/xml")
        # A failure here can come back as 200 with an <Error> body.
        if b"<Error>" in data[:200]:
            raise S3Error(f"{self.host} did not complete the upload of {key}")

    def abort_upload(self, key: str, upload_id: str) -> None:
        try:
            self._call("DELETE", key, query=[("uploadId", upload_id)])
        except S3Error:
            pass


class Uploader(io.RawIOBase):
    """A file to write an object into: what is written goes up as it comes.

    Under a part's worth it is one PUT when closed; past that, a multipart
    upload, a part at a time, with the one part in memory. The SHA-256 and
    the size of everything written are kept, for the manifest.
    """

    def __init__(
        self, bucket: Bucket, key: str, *, part_size: int = PART_SIZE, content_type: str = "application/octet-stream"
    ) -> None:
        super().__init__()
        self.bucket = bucket
        self.key = key
        self.part_size = part_size
        self.content_type = content_type
        self.size = 0
        self._hash = hashlib.sha256()
        self._buffer = bytearray()
        self._upload_id = ""
        self._etags: list[str] = []
        self._done = False

    def writable(self) -> bool:
        return True

    def write(self, data) -> int:  # type: ignore[override]
        view = memoryview(data).tobytes()
        self._buffer.extend(view)
        self._hash.update(view)
        self.size += len(view)
        while len(self._buffer) >= self.part_size:
            self._send(bytes(self._buffer[: self.part_size]))
            del self._buffer[: self.part_size]
        return len(view)

    def _send(self, part: bytes) -> None:
        if not self._upload_id:
            self._upload_id = self.bucket.begin_upload(self.key, self.content_type)
        self._etags.append(self.bucket.upload_part(self.key, self._upload_id, len(self._etags) + 1, part))

    @property
    def sha256(self) -> str:
        return self._hash.hexdigest()

    def finish(self) -> None:
        """Send what is left and complete the object. Called by close."""
        if self._done:
            return
        self._done = True
        if not self._upload_id:
            self.bucket.put(self.key, bytes(self._buffer), self.content_type)
        else:
            if self._buffer:
                self._send(bytes(self._buffer))
            self.bucket.complete_upload(self.key, self._upload_id, self._etags)
        self._buffer = bytearray()

    def abandon(self) -> None:
        """Leave nothing behind: a backup that failed half way is no backup."""
        self._done = True
        if self._upload_id:
            self.bucket.abort_upload(self.key, self._upload_id)
        self._buffer = bytearray()

    def close(self) -> None:
        if not self.closed:
            try:
                self.finish()
            finally:
                super().close()


def read_chunks(response, size: int = 1024 * 1024) -> Iterator[bytes]:
    """An open response, a chunk at a time, closed at the end."""
    with response:
        while True:
            chunk = response.read(size)
            if not chunk:
                return
            yield chunk
