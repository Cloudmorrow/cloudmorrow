"""Profile photos: whatever comes in is kept as a small square, and served cached."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from cloudmorrow.server.photos import EDGE, PhotoError, PhotoStore, shrink
from tests.conftest import ADMIN, GUEST


def picture(width: int = 4000, height: int = 3000, kind: str = "JPEG", colour=(200, 40, 40)) -> bytes:
    """A camera-sized picture with noise in it, so it does not compress to nothing."""
    import random

    rng = random.Random(1)
    image = Image.new("RGB", (width, height), colour)
    pixels = image.load()
    for _ in range(20000):
        pixels[rng.randrange(width), rng.randrange(height)] = (rng.randrange(256),) * 3
    out = io.BytesIO()
    image.save(out, kind, quality=95)
    return out.getvalue()


def test_a_big_photo_is_kept_small_and_square():
    big = picture()
    small = shrink(big)
    with Image.open(io.BytesIO(small)) as image:
        assert image.format == "WEBP"
        assert image.size == (EDGE, EDGE)
    assert len(small) < 40_000 < len(big)


def test_a_tall_photo_keeps_its_middle():
    out = io.BytesIO()
    image = Image.new("RGB", (100, 300), (0, 0, 255))
    image.paste((255, 0, 0), (0, 100, 100, 200))  # the middle third is red
    image.save(out, "PNG")
    with Image.open(io.BytesIO(shrink(out.getvalue()))) as square:
        red, green, blue = square.convert("RGB").getpixel((EDGE // 2, EDGE // 2))
        assert red > 200 and blue < 60


def test_the_way_the_camera_was_held_is_kept():
    image = Image.new("RGB", (400, 200), (0, 200, 0))
    exif = image.getexif()
    exif[0x0112] = 6  # turned a quarter
    out = io.BytesIO()
    image.save(out, "JPEG", exif=exif)
    with Image.open(io.BytesIO(shrink(out.getvalue()))) as square:
        assert square.size == (EDGE, EDGE)


def test_what_is_not_a_picture_is_refused():
    with pytest.raises(PhotoError):
        shrink(b"not a picture at all")
    with pytest.raises(PhotoError):
        shrink(b"")


def test_upload_show_and_remove(client, auth, guest_auth, users):
    assert client.get("/api/auth/me", headers=auth).json()["photo"] == ""
    answer = client.put("/api/auth/photo", content=picture(), headers=auth)
    assert answer.status_code == 200, answer.text
    stamp = answer.json()["photo"]
    assert stamp and client.get("/api/auth/me", headers=auth).json()["photo"] == stamp

    # Everybody signed in sees who has one, and the photo itself.
    assert client.get("/api/people/photos", headers=guest_auth).json() == {ADMIN[0]: stamp}
    people = client.get("/api/people", headers=guest_auth).json()
    assert {p["username"]: p["photo"] for p in people}[ADMIN[0]] == stamp
    shown = client.get(f"/api/people/{ADMIN[0]}/photo?v={stamp}", headers=guest_auth)
    assert shown.status_code == 200
    assert shown.headers["content-type"] == "image/webp"
    assert "immutable" in shown.headers["cache-control"]
    assert len(shown.content) < 40_000
    # Without the stamp it is asked again each time, and answered short when unchanged.
    plain = client.get(f"/api/people/{ADMIN[0]}/photo", headers=guest_auth)
    assert "no-cache" in plain.headers["cache-control"]
    again = client.get(f"/api/people/{ADMIN[0]}/photo", headers={**guest_auth, "If-None-Match": plain.headers["etag"]})
    assert again.status_code == 304

    # A new photo is a new stamp.
    newer = client.put("/api/auth/photo", content=picture(colour=(10, 10, 200)), headers=auth).json()["photo"]
    assert newer != stamp

    assert client.delete("/api/auth/photo", headers=auth).status_code == 204
    assert client.get("/api/auth/me", headers=auth).json()["photo"] == ""
    assert client.get(f"/api/people/{ADMIN[0]}/photo", headers=guest_auth).status_code == 404
    assert client.get("/api/people/photos", headers=guest_auth).json() == {}


def test_a_bad_upload_is_refused(client, auth):
    answer = client.put("/api/auth/photo", content=b"hello", headers=auth)
    assert answer.status_code == 422
    assert client.get("/api/auth/me", headers=auth).json()["photo"] == ""


def test_signed_out_sees_nothing(client):
    assert client.get(f"/api/people/{ADMIN[0]}/photo").status_code == 401
    assert client.put("/api/auth/photo", content=picture(40, 40)).status_code == 401


def test_a_deleted_account_takes_its_photo(users):
    photos = PhotoStore(users)
    photos.put(GUEST[0], picture(300, 300))
    assert photos.get(GUEST[0]) is not None
    users.delete(GUEST[0])
    assert photos.get(GUEST[0]) is None


def test_the_web_app_lays_photos_over_initials():
    from pathlib import Path

    web = Path(__file__).resolve().parents[1] / "src" / "cloudmorrow" / "server" / "web"
    assert 'import "./photos.js";' in (web / "app.js").read_text()
    assert '@import "./photos.css";' in (web / "app.css").read_text()
    # Every person's mark says whose it is, so the photo can find it.
    for name in ("admin.js", "kit_space.js"):
        assert 'class="avatar"' not in (web / name).read_text(), name
    assert 'data-photo="${esc(session.user)}"' in (web / "core.js").read_text()
    me = (web / "me.js").read_text()
    # Shrunk on the device before it goes up, and asked before it is removed.
    assert "createImageBitmap" in me and '"/api/auth/photo"' in me
    assert "await ask(" in me
