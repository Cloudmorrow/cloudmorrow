"""Runtimes: a program a Quill needs, fetched for it at install, on its services' PATH,
offered for removal with the last Quill that needs it. Nothing here reaches the network:
the "build" is a tarball made for the test, and the catalog is written beside it."""

from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path

import pytest

from cloudmorrow.server.quills import QuillError, QuillRegistry, load_catalog, parse_manifest, removal
from cloudmorrow.server.quills.runtimes import RuntimeStore, check_runtime, platform_of, said_size
from cloudmorrow.server.records import RecordStore
from tests.conftest import ADMIN, QUILL_CATALOG, token_for
from tests.test_quills import write_quill

CLIPS = """
[quill]
id = "clips"
name = "Clips"
version = "1.0.0"
summary = "Blurs faces in a video."
category = "personal"
publisher = "Cloudmorrow"
license = "AGPL-3.0-or-later"

[uses]
datamodels = ["file"]

[requires]
runtimes = ["ffmpeg"]

[[services]]
id = "render"
command = ["python", "services/render.py"]
always = true
"""

SLIDES = CLIPS.replace('id = "clips"', 'id = "slides"').replace('name = "Clips"', 'name = "Slides"')


def fake_build(folder: Path, version: str = "7.1.5") -> tuple[Path, str, int]:
    """A tar.xz the shape of a static ffmpeg release: a folder with bin/ffmpeg and bin/ffprobe."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"ffmpeg-{version}.tar.xz"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:xz") as archive:
        for program in ("ffmpeg", "ffprobe"):
            body = f'#!/bin/sh\necho "{program} {version}"\n'.encode()
            info = tarfile.TarInfo(f"ffmpeg-{version}-static/bin/{program}")
            info.size = len(body)
            info.mode = 0o644  # the store makes it executable
            archive.addfile(info, io.BytesIO(body))
        readme = b"a fake ffmpeg for the tests\n"
        info = tarfile.TarInfo(f"ffmpeg-{version}-static/README.txt")
        info.size = len(readme)
        archive.addfile(info, io.BytesIO(readme))
    data = buffer.getvalue()
    path.write_bytes(data)
    return path, hashlib.sha256(data).hexdigest(), len(data)


def write_catalog(
    folder: Path, build: tuple[Path, str, int] | None, *, sha256: str = "", version: str = "7.1.5"
) -> Path:
    """A catalog beside the build, with this machine's OS and architecture as its one build."""
    os_name, arch = platform_of()
    folder.mkdir(parents=True, exist_ok=True)
    runtime = ""
    if build is not None:
        path, digest, size = build
        runtime = f"""
[runtimes.ffmpeg]
label = "ffmpeg"
summary = "Reads, writes and converts video and sound."
version = "{version}"
license = "GPL-3.0-or-later"
homepage = "https://ffmpeg.org"

[[runtimes.ffmpeg.builds]]
os = "{os_name}"
arch = "{arch}"
url = "{path.relative_to(folder) if path.is_relative_to(folder) else path}"
sha256 = "{sha256 or digest}"
size = {size}
programs = ["ffmpeg", "ffprobe"]
"""
    (folder / "catalog.toml").write_text(
        f"""
[datamodels]
repo = "{QUILL_CATALOG / "datamodels"}"

[[categories]]
id = "personal"
label = "Personal"
description = "Yours."
{runtime}
""",
        encoding="utf-8",
    )
    return folder


@pytest.fixture()
def catalog_dir(tmp_path) -> Path:
    return write_catalog(tmp_path / "catalog", fake_build(tmp_path / "catalog" / "builds"))


@pytest.fixture()
def registry(tmp_path, catalog_dir) -> QuillRegistry:
    return QuillRegistry(
        tmp_path / "quills",
        tmp_path / "datamodels",
        str(catalog_dir),
        runtimes=RuntimeStore(tmp_path / "runtimes"),
    )


# -- the manifest -----------------------------------------------------------------------
def test_requires_is_read_and_held_to_its_shape(tmp_path):
    manifest = parse_manifest(__import__("tomllib").loads(CLIPS))
    assert manifest.runtimes == ("ffmpeg",)
    assert manifest.to_dict()["requires"] == {"runtimes": ["ffmpeg"], "quills": []}
    # Without services too: the server itself draws a picture of each video with ffmpeg.
    assert parse_manifest(__import__("tomllib").loads(CLIPS.split("[[services]]")[0])).runtimes == ("ffmpeg",)
    with pytest.raises(QuillError, match="runtime ids"):
        parse_manifest(__import__("tomllib").loads(CLIPS.replace('["ffmpeg"]', '["FFmpeg 7"]')))
    with pytest.raises(QuillError, match="knows runtimes"):
        parse_manifest(__import__("tomllib").loads(CLIPS.replace("[requires]", "[requires]\npackages = []")))
    with pytest.raises(QuillError, match="twice"):
        parse_manifest(__import__("tomllib").loads(CLIPS.replace('["ffmpeg"]', '["ffmpeg", "ffmpeg"]')))


# -- the catalog ------------------------------------------------------------------------
def test_the_catalog_describes_a_runtime_and_refuses_a_bad_one(catalog_dir):
    catalog = load_catalog(str(catalog_dir))
    assert catalog.runtimes["ffmpeg"]["label"] == "ffmpeg"
    assert catalog.runtimes["ffmpeg"]["builds"][0]["programs"] == ["ffmpeg", "ffprobe"]
    good = dict(catalog.runtimes["ffmpeg"])
    check_runtime("ffmpeg", good)
    with pytest.raises(QuillError, match="sha256"):
        check_runtime("ffmpeg", {**good, "builds": [{**good["builds"][0], "sha256": "abc"}]})
    with pytest.raises(QuillError, match="os is one of"):
        check_runtime("ffmpeg", {**good, "builds": [{**good["builds"][0], "os": "plan9"}]})
    with pytest.raises(QuillError, match="programs"):
        check_runtime("ffmpeg", {**good, "builds": [{**good["builds"][0], "programs": []}]})
    with pytest.raises(QuillError, match="a name"):
        check_runtime("ffmpeg", {**good, "builds": [{**good["builds"][0], "programs": ["../sh"]}]})
    with pytest.raises(QuillError, match="two builds"):
        check_runtime("ffmpeg", {**good, "builds": [good["builds"][0], good["builds"][0]]})
    with pytest.raises(QuillError, match="needs a label"):
        check_runtime("ffmpeg", {**good, "label": ""})
    with pytest.raises(QuillError, match="lowercase"):
        check_runtime("FFmpeg", good)
    assert said_size(119007364) == "119 MB" and said_size(1_500_000_000) == "1.5 GB" and said_size(10) == "1 MB"


# -- the store --------------------------------------------------------------------------
def test_a_runtime_is_fetched_checked_unpacked_and_its_programs_linked(tmp_path, catalog_dir):
    store = RuntimeStore(tmp_path / "runtimes")
    catalog = load_catalog(str(catalog_dir))
    assert store.installed() == {} and store.missing(["ffmpeg"]) == ["ffmpeg"]
    fetched = store.ensure(["ffmpeg"], catalog.runtimes, base=catalog.base)
    assert fetched == ["ffmpeg"]
    info = store.info("ffmpeg")
    assert info["version"] == "7.1.5" and set(info["programs"]) == {"ffmpeg", "ffprobe"}
    ffmpeg = store.bin_dir("ffmpeg") / "ffmpeg"
    assert ffmpeg.is_symlink() and ffmpeg.resolve().is_file()
    import subprocess

    assert subprocess.run([str(ffmpeg)], capture_output=True, text=True, check=True).stdout.strip() == "ffmpeg 7.1.5"
    assert store.path_for(["ffmpeg", "nope"]) == [str(store.bin_dir("ffmpeg"))]
    # Here already at this checksum: nothing is fetched again.
    assert store.ensure(["ffmpeg"], catalog.runtimes, base=catalog.base) == []
    assert store.remove("ffmpeg") is True and store.remove("ffmpeg") is False
    assert store.installed() == {}


def test_a_download_that_does_not_match_the_catalog_installs_nothing(tmp_path):
    build = fake_build(tmp_path / "catalog" / "builds")
    catalog = load_catalog(str(write_catalog(tmp_path / "catalog", build, sha256="0" * 64)))
    store = RuntimeStore(tmp_path / "runtimes")
    with pytest.raises(QuillError, match="checksum differs"):
        store.ensure(["ffmpeg"], catalog.runtimes, base=catalog.base)
    assert store.installed() == {} and not list((tmp_path / "runtimes").glob(".*"))


def test_no_catalog_no_build_and_no_such_runtime_are_each_said(tmp_path, catalog_dir):
    store = RuntimeStore(tmp_path / "runtimes")
    catalog = load_catalog(str(catalog_dir))
    with pytest.raises(QuillError, match="could not be read"):
        store.ensure(["ffmpeg"], None)
    with pytest.raises(QuillError, match="catalog does not have"):
        store.ensure(["gimp"], catalog.runtimes, base=catalog.base)
    elsewhere = RuntimeStore(tmp_path / "runtimes")
    elsewhere.os_name, elsewhere.arch = "windows", "x86"
    with pytest.raises(QuillError, match="no build of ffmpeg for this server"):
        elsewhere.ensure(["ffmpeg"], catalog.runtimes, base=catalog.base)
    rows = elsewhere.describe(["ffmpeg"], catalog.runtimes)
    assert rows[0]["available"] is False and "no build" in rows[0]["problem"]
    offline = store.describe(["ffmpeg"], None)
    assert offline[0]["id"] == "ffmpeg" and "catalog could not be read" in offline[0]["problem"]


# -- the registry: the sheet, the install, the removal ------------------------------------
def test_the_install_sheet_says_what_is_added_and_the_install_fetches_it(registry, tmp_path):
    folder = write_quill(tmp_path / "src", CLIPS)
    plan = registry.plan(folder, QUILL_CATALOG / "datamodels")
    assert plan["requires"] == {"runtimes": ["ffmpeg"], "quills": []}
    [row] = plan["runtimes"]
    assert row["label"] == "ffmpeg" and row["version"] == "7.1.5" and row["available"] is True
    assert row["installed"] == "" and row["size"] > 0 and row["license"] == "GPL-3.0-or-later"
    # Planning fetches nothing.
    assert registry.runtimes.installed() == {}

    done = registry.install(folder, QUILL_CATALOG / "datamodels")
    assert done["runtimes_fetched"] == ["ffmpeg"] and done["runtimes"][0]["installed"] == "7.1.5"
    assert (registry.runtimes.bin_dir("ffmpeg") / "ffprobe").exists()
    # Installed again: the sheet says it is here, and nothing is fetched.
    again = registry.install(folder, QUILL_CATALOG / "datamodels")
    assert again["runtimes_fetched"] == [] and again["runtimes"][0]["installed"] == "7.1.5"


def test_a_runtime_the_catalog_lacks_is_refused_before_anything_is_installed(registry, tmp_path):
    folder = write_quill(tmp_path / "src", CLIPS.replace('["ffmpeg"]', '["gimp"]'))
    with pytest.raises(QuillError, match="catalog does not have"):
        registry.plan(folder, QUILL_CATALOG / "datamodels")
    with pytest.raises(QuillError, match="catalog does not have"):
        registry.install(folder, QUILL_CATALOG / "datamodels")
    assert registry.quills == {}


def test_without_a_catalog_the_quill_installs_and_its_service_waits_for_the_runtime(tmp_path):
    # A test harness, an offline check, a server whose catalog is unreachable:
    # nothing is fetched, nothing is refused, and the service says what it waits for.
    registry = QuillRegistry(tmp_path / "quills", tmp_path / "datamodels", str(tmp_path / "no-catalog"))
    folder = write_quill(tmp_path / "src", CLIPS)
    plan = registry.plan(folder, QUILL_CATALOG / "datamodels")
    assert "catalog could not be read" in plan["runtimes"][0]["problem"]
    done = registry.install(folder, QUILL_CATALOG / "datamodels")
    assert done["runtimes_fetched"] == [] and done["runtimes_skipped"] == ["ffmpeg"]
    assert "clips" in registry.quills and registry.runtimes.installed() == {}
    assert registry.runtimes.missing(registry.quills["clips"].runtimes) == ["ffmpeg"]


def test_the_remove_sheet_offers_a_runtime_only_when_nothing_else_needs_it(registry, tmp_path):
    registry.install(write_quill(tmp_path / "a", CLIPS), QUILL_CATALOG / "datamodels")
    registry.install(write_quill(tmp_path / "b", SLIDES), QUILL_CATALOG / "datamodels")
    store = RecordStore(tmp_path / "cm.db", registry.models, registry.expiries)
    # Slides needs ffmpeg too, so removing Clips does not offer it.
    assert removal.brought(registry, store, "clips") == []
    assert removal.remove(registry, store, "clips") == {"dropped": {}}
    assert registry.runtimes.info("ffmpeg") is not None
    # Slides is the last one: the sheet offers ffmpeg, with its size.
    [row] = removal.brought(registry, store, "slides")
    assert row["id"] == "runtime:ffmpeg" and row["kind"] == "runtime" and row["label"] == "ffmpeg 7.1.5"
    assert row["records"] == 0 and row["size"] > 0 and row["size_said"] == "1 MB"
    # Kept unless dropped.
    registry.install(write_quill(tmp_path / "a", CLIPS), QUILL_CATALOG / "datamodels")
    assert removal.remove(registry, store, "slides") == {"dropped": {}}
    assert registry.runtimes.info("ffmpeg") is not None
    gone = removal.remove(registry, store, "clips", ["runtime:ffmpeg"])
    assert gone == {"dropped": {}, "runtimes": ["ffmpeg"]}
    assert registry.runtimes.installed() == {} and registry.quills == {}


def test_only_a_runtime_it_brought_can_be_dropped(registry, tmp_path):
    registry.install(write_quill(tmp_path / "a", CLIPS), QUILL_CATALOG / "datamodels")
    store = RecordStore(tmp_path / "cm.db", registry.models, registry.expiries)
    with pytest.raises(QuillError, match="did not bring runtime:gimp"):
        removal.remove(registry, store, "clips", ["runtime:gimp"])


# -- the services -----------------------------------------------------------------------
def test_a_service_finds_its_runtime_first_on_the_path_and_waits_without_it(client, tmp_path):
    state = client.app.state.cloudmorrow
    catalog_dir = write_catalog(tmp_path / "catalog", fake_build(tmp_path / "catalog" / "builds"))
    object.__setattr__(state.config, "quill_catalog", str(catalog_dir))
    state.quills.catalog_location = str(catalog_dir)
    auth = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    folder = write_quill(tmp_path / "src", CLIPS)

    sheet = client.post("/api/quills/plan", json={"source": str(folder)}, headers=auth)
    assert sheet.status_code == 200, sheet.text
    assert sheet.json()["runtimes"][0] | {"size": 0} == {
        "id": "ffmpeg",
        "label": "ffmpeg",
        "summary": "Reads, writes and converts video and sound.",
        "version": "7.1.5",
        "license": "GPL-3.0-or-later",
        "homepage": "https://ffmpeg.org",
        "size": 0,
        "installed": "",
        "available": True,
        "problem": "",
    }
    made = client.post("/api/quills", json={"source": str(folder)}, headers=auth)
    assert made.status_code == 201, made.text
    assert made.json()["runtimes_fetched"] == ["ffmpeg"]
    bin_dir = state.quills.runtimes.bin_dir("ffmpeg")
    assert bin_dir.is_dir()
    # Installed, the Quill is told with its runtime as it is here.
    told = client.get("/api/quills/clips", headers=auth).json()
    assert [(r["id"], r["installed"], r["available"]) for r in told["runtimes"]] == [("ffmpeg", "7.1.5", True)]

    environment = state.services.environment("clips", "render", 0)
    assert environment["PATH"].split(__import__("os").pathsep)[0] == str(bin_dir)

    # The runtime gone from disk (a restore of the data without it): the
    # service waits, and the state says what for, rather than failing in a loop.
    state.quills.runtimes.remove("ffmpeg")
    state.services.reconcile()
    [clips] = [row for row in state.services.status() if row["id"] == "clips"]
    [render] = clips["services"]
    assert render["state"] == "stopped" and "needs ffmpeg" in render["problem"]
    [row] = client.get("/api/quills/clips", headers=auth).json()["runtimes"]
    assert row["installed"] == "" and "not on this server" in row["problem"]

    # Over the API: the remove sheet lists it once it is back, and the drop takes it away.
    state.quills.runtimes.ensure(["ffmpeg"], load_catalog(str(catalog_dir)).runtimes, base=catalog_dir)
    brought = client.get("/api/quills/clips/brought", headers=auth).json()
    assert [(b["id"], b["kind"]) for b in brought] == [("runtime:ffmpeg", "runtime")]
    removed = client.delete("/api/quills/clips?drop=runtime:ffmpeg", headers=auth)
    assert removed.status_code == 200 and removed.json() == {"dropped": {}, "runtimes": ["ffmpeg"]}
    assert not bin_dir.exists()


# -- on a person's machine ----------------------------------------------------------------
CONVERT = """
[quill]
id = "convert"
name = "Convert"
version = "1.0.0"
summary = "Converts the videos in a folder of yours."
category = "personal"
publisher = "Cloudmorrow"
license = "AGPL-3.0-or-later"
code = "quill.py"

[uses]
datamodels = ["file"]

[[machine]]
id = "convert"
why = "to convert the videos in a folder you pick"
[machine.needs]
folders = [{ name = "videos", access = "read" }]
runtimes = ["ffmpeg"]
"""

CONVERT_CODE = """
from cloudmorrow.quill import machine


@machine
def convert(ctx):
    done = ctx.run(["ffmpeg", "-version"])
    return {"out": done["out"].strip(), "code": done["code"]}
"""


def write_convert(folder: Path, manifest: str = CONVERT) -> Path:
    write_quill(folder, manifest)
    (folder / "quill.py").write_text(CONVERT_CODE, encoding="utf-8")
    return folder


def test_a_machine_handler_names_the_runtimes_it_needs(registry, tmp_path):
    manifest = parse_manifest(__import__("tomllib").loads(CONVERT), write_convert(tmp_path / "src"))
    assert manifest.machine[0]["runtimes"] == ["ffmpeg"] and manifest.machine_runtimes == ("ffmpeg",)
    assert manifest.runtimes == ()  # the server fetches nothing for a machine handler
    with pytest.raises(QuillError, match="needs.runtimes"):
        parse_manifest(__import__("tomllib").loads(CONVERT.replace('["ffmpeg"]', '["FF mpeg"]')), tmp_path / "src")
    # The install sheet says what a machine would fetch, and refuses a runtime the catalog lacks.
    plan = registry.plan(tmp_path / "src", QUILL_CATALOG / "datamodels")
    assert plan["runtimes"] == []
    [row] = plan["machine_runtimes"]
    assert row["label"] == "ffmpeg" and row["version"] == "7.1.5" and row["size"] > 0 and row["platforms"]
    registry.install(tmp_path / "src", QUILL_CATALOG / "datamodels")
    assert registry.runtimes.installed() == {}
    with pytest.raises(QuillError, match="catalog does not have"):
        registry.plan(
            write_convert(tmp_path / "gimp", CONVERT.replace('["ffmpeg"]', '["gimp"]')), QUILL_CATALOG / "datamodels"
        )


def _machine(client, tmp_path, catalog_dir):
    """An agent for the admin, with Convert switched on, against the test client."""
    from cloudmorrow.agent.client import AgentClient
    from cloudmorrow.agent.config import AgentConfig
    from cloudmorrow.agent.quills import MachineQuills
    from cloudmorrow.sandbox import InProcessGuest

    state = client.app.state.cloudmorrow
    object.__setattr__(state.config, "quill_catalog", str(catalog_dir))
    state.quills.catalog_location = str(catalog_dir)
    state.quills.install(
        write_convert(tmp_path / "src"), QUILL_CATALOG / "datamodels", origin={"installed_by": ADMIN[0]}
    )
    _, token = state.agents.enroll_for_user(ADMIN[0], name="laptop")
    videos = tmp_path / "Videos"
    videos.mkdir(exist_ok=True)
    config = AgentConfig(server_url="http://testserver", agent_token=token, allow_insecure_http=True)
    config.path = tmp_path / "agent.toml"
    config.quills = {"convert": {"convert": {"folders": {"videos": str(videos)}}}}
    config.save()
    agent = AgentClient(config)
    agent._client = client
    agent._client.headers["User-Agent"] = "cloudmorrow-agent/test"
    return MachineQuills(config, agent, base=tmp_path / "agent" / "quills", guest=InProcessGuest), state


def test_a_machine_fetches_the_runtime_its_handler_needs_and_runs_its_program(client, tmp_path):
    catalog_dir = write_catalog(tmp_path / "catalog", fake_build(tmp_path / "catalog" / "builds"))
    machine, state = _machine(client, tmp_path, catalog_dir)
    # The server tells the agent what the catalog knows, and fetches nothing itself.
    assert "ffmpeg" in machine.client.runtimes()
    assert state.quills.runtimes.installed() == {}
    assert machine.runtimes.installed() == {}
    # Switching on fetches it (the CLI does this after the yes); a run would too.
    assert machine.ensure_runtimes({"runtimes": ["ffmpeg"]}) == ["ffmpeg"]
    assert machine.runtimes.info("ffmpeg")["version"] == "7.1.5"
    assert machine.ensure_runtimes({"runtimes": ["ffmpeg"]}) == []
    # ffmpeg is not in quill_programs, and needs no needs.run: it is the handler's own.
    assert machine.config.quill_programs == []
    assert machine.run("convert", "convert") == {"out": "ffmpeg 7.1.5", "code": 0}
    # Anything else still needs the manifest and the machine to agree.
    with pytest.raises(sdk_refused()):
        machine._program({"runtimes": ["ffmpeg"], "run": []}, {"command": ["ls"]})
    # The runtime goes with the last handler that needs it, when the person says so.
    assert [r["id"] for r in machine.unused_runtimes("convert", "convert")] == ["ffmpeg"]
    # The data folder wiped (a new machine, restored config): a run fetches it again.
    machine.runtimes.remove("ffmpeg")
    assert machine.run("convert", "convert")["out"] == "ffmpeg 7.1.5"


def sdk_refused():
    from cloudmorrow.quill import context as sdk

    return sdk.Refused
