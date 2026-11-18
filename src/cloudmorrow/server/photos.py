"""People's profile photos: one small square each, kept in the database.

Whatever comes in, a phone's 5 MB picture or a scanned poster, is turned
the way the camera held it, cut to the square in its middle and scaled to
EDGE pixels a side, then kept as a WebP of ten or twenty kilobytes. That
is all that is ever sent out, so a list of fifty people costs a list of
fifty small pictures, and the browser keeps each one: its address carries
the photo's stamp, which changes when the photo does.

They live in the database rather than beside it so a backup has them and
every host of a server sees the same ones. The table holds the picture as
base64 text, the one column type both engines read the same way; the
stamp is on the person too (`users.photo`), so a list of people says who
has one without reading a picture.
"""

from __future__ import annotations

import base64
import hashlib
import io
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cloudmorrow.server.db import UserStore

# The side of the square kept: twice the biggest it is drawn (56 px on Me),
# and a little over, for a sharp picture on any screen.
EDGE = 256
# What may come in. A phone's photo is 2–8 MB; the web app shrinks it before
# it is sent, so this only stops something that is not a photo at all.
MAX_UPLOAD = 25 * 1024 * 1024
# A picture with more pixels than this is refused before it is decoded.
MAX_PIXELS = 80_000_000
CONTENT_TYPE = "image/webp"

TABLES = """
CREATE TABLE IF NOT EXISTS user_photos (
    username TEXT PRIMARY KEY,
    stamp    TEXT NOT NULL,
    data     TEXT NOT NULL
);
"""


class PhotoError(ValueError):
    """Not a picture this server can read, or too big to try."""


class PhotoUnavailable(RuntimeError):
    """Pillow is not installed on the server."""


def shrink(data: bytes, edge: int = EDGE) -> bytes:
    """*data*, any picture Pillow reads, as an *edge* × *edge* WebP."""
    if not data:
        raise PhotoError("there is no picture in that")
    if len(data) > MAX_UPLOAD:
        raise PhotoError("that picture is too big")
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise PhotoUnavailable("Pillow is not installed on the server") from exc
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            if width * height > MAX_PIXELS:
                raise PhotoError("that picture has too many pixels")
            # A JPEG can be decoded at a fraction of its size when only a
            # small picture is wanted: much less work for the same result.
            image.draft("RGB", (edge * 2, edge * 2))
            image = ImageOps.exif_transpose(image) or image
            # The middle square, scaled: a face is nearly always there.
            image = ImageOps.fit(image, (edge, edge), Image.Resampling.LANCZOS)
            if image.mode in ("RGBA", "LA", "P", "PA"):
                image = image.convert("RGBA")
            elif image.mode != "RGB":
                image = image.convert("RGB")
            out = io.BytesIO()
            image.save(out, "WEBP", quality=82, method=4)
    except PhotoError:
        raise
    except Exception as exc:  # noqa: BLE001 - not a picture, or one Pillow cannot read
        raise PhotoError("that is not a picture this server can read") from exc
    return out.getvalue()


class PhotoStore:
    """The photos, beside the people they are of."""

    def __init__(self, users: UserStore) -> None:
        self.users = users

    def _connect(self):
        return self.users.db.connect()

    def get(self, username: str) -> tuple[bytes, str] | None:
        """The photo and its stamp, or None when they have none."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT stamp, data FROM user_photos WHERE username = ?", (username.strip().lower(),)
            ).fetchone()
        return (base64.b64decode(row["data"]), row["stamp"]) if row else None

    def put(self, username: str, data: bytes) -> str:
        """Keep *data*, shrunk, as *username*'s photo. Answers its stamp."""
        username = self.users.require(username).username
        picture = shrink(data)
        stamp = hashlib.sha256(picture).hexdigest()[:16]
        with self._connect() as conn:
            conn.execute("DELETE FROM user_photos WHERE username = ?", (username,))
            conn.execute(
                "INSERT INTO user_photos (username, stamp, data) VALUES (?, ?, ?)",
                (username, stamp, base64.b64encode(picture).decode("ascii")),
            )
        self.users.update(username, photo=stamp)
        return stamp

    def remove(self, username: str) -> None:
        username = self.users.require(username).username
        with self._connect() as conn:
            conn.execute("DELETE FROM user_photos WHERE username = ?", (username,))
        self.users.update(username, photo="")

    def stamps(self) -> dict[str, str]:
        """Who has a photo, and its stamp."""
        return {u.username: u.photo for u in self.users.list() if u.photo}
