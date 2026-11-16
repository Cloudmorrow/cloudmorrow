"""scripts/announce.py: the post, the link facets, and skipping with no key."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import announce  # noqa: E402


def test_the_post_is_the_subject_and_the_address():
    text = announce.post_text("v0.94.0", "v0.94.0: the drive under Folders", "https://x/releases/tag/v0.94.0")
    assert text == "Cloudmorrow v0.94.0: The drive under Folders\n\nhttps://x/releases/tag/v0.94.0"
    assert announce.post_text("v1.0.0", "v1.0.0", "https://x").startswith("Cloudmorrow v1.0.0: V1.0.0")


def test_bluesky_facets_are_byte_offsets():
    text = "Cloudmorrow v0.94.0: Æblegrød\n\nhttps://a/b"
    [facet] = announce.bluesky_facets(text)
    raw = text.encode()
    assert raw[facet["index"]["byteStart"] : facet["index"]["byteEnd"]] == b"https://a/b"
    assert facet["features"][0]["uri"] == "https://a/b"


def test_no_key_means_skipped_not_failed(capsys):
    assert announce.mastodon("x", {}) == "mastodon: no key, skipped"
    assert announce.bluesky("x", {}) == "bluesky: no key, skipped"
    assert announce.main(["v0.1.0", "v0.1.0: hello", "https://x", "--dry-run"]) == 0
    assert "Cloudmorrow v0.1.0: Hello" in capsys.readouterr().out
