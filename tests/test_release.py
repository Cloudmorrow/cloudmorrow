"""The release script's arithmetic, and what a deploy calls each of its ends.

A release is a git tag and the version is read back off it, so the only thing
with an opinion is which tag comes next — which is this.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from cloudmorrow.cli.update import _name

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release.py"


def load():
    spec = importlib.util.spec_from_file_location("release", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load()


# -- which tag comes next ----------------------------------------------------


def test_a_push_takes_the_next_minor():
    assert release.nxt((0, 6, 0), major=False) == "v0.7.0"


def test_a_major_takes_the_next_major_and_resets_the_minor():
    assert release.nxt((0, 6, 0), major=True) == "v1.0.0"


def test_the_first_release_is_v0_1_0():
    assert release.nxt((0, 0, 0), major=False) == "v0.1.0"


def test_the_minor_does_not_roll_over_at_ten():
    """Nothing here is decimal: 0.9.0 is followed by 0.10.0, not 1.0.0."""
    assert release.nxt((0, 9, 0), major=False) == "v0.10.0"


def test_a_major_release_keeps_counting_minors_after_it():
    assert release.nxt((1, 0, 0), major=False) == "v1.1.0"


@pytest.mark.parametrize(
    "tag, parsed",
    [("v0.1.0", (0, 1, 0)), ("v1.10.3", (1, 10, 3)), ("v12.0.0", (12, 0, 0))],
)
def test_a_release_tag_is_read_back_as_numbers(tag, parsed):
    assert tuple(int(part) for part in release.TAG.match(tag).groups()) == parsed


@pytest.mark.parametrize("tag", ["v1.2", "1.2.0", "v1.2.0-rc1", "version-1", "vx.y.z"])
def test_what_is_not_a_release_tag(tag):
    """Only `vX.Y.Z` counts, so an unrelated tag cannot move the version."""
    assert release.TAG.match(tag) is None


# -- what a deploy calls itself ----------------------------------------------


def test_a_tagged_deploy_is_named_by_its_release():
    result = {"new_version": "0.7.0", "new_commit": "1c91c8babcdef"}
    assert _name(result, "new") == "v0.7.0"


def test_an_untagged_deploy_falls_back_to_the_commit():
    result = {"new_version": "", "new_commit": "1c91c8babcdef"}
    assert _name(result, "new") == "1c91c8ba"


def test_a_dev_version_is_not_shown_as_a_release():
    """`0.8.0.dev3` is work towards a release, and must not read as one."""
    result = {"new_version": "0.8.0.dev3+g1c91c8b", "new_commit": "1c91c8babcdef"}
    assert _name(result, "new") == "1c91c8ba"


def test_an_older_server_that_sends_no_version_still_names_the_deploy():
    """The field is new; a server from before it must not crash the client."""
    assert _name({"old_commit": "deadbeefcafe"}, "old") == "deadbeef"
