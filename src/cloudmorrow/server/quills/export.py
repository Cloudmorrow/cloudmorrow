"""A Quill of somebody's own, on its way out: exported in the template's shape, or forked.

A personal Quill was born on the server, written by an assistant into a
folder, with no repository behind it. To go further — to be published, or
worked on with `cm quill test` — it needs the shape the template gives a
new Quill: tests, a CLAUDE.md with the skills, a pyproject, the workflows.
`export` writes the folder as it is (its datamodels under the names its
files use; the owner's prefix was only ever the server's reading of them)
and adds what the template has that the folder lacks. Nothing of the
server's goes with it: no records unless chosen as a dataset, no secret, no
name of anybody.

`fork` is the other direction: somebody takes a Quill they have into one of
their own under a new id, to change it. It is a copy with the id renamed in
the manifest, the datamodels and the code — a textual rename, said so.

See docs/SHARING.md, *Published* and *Forked*.
"""

from __future__ import annotations

import io
import re
import shutil
import tarfile
from pathlib import Path

import tomli_w

from cloudmorrow.quill_reference import quill_reference
from cloudmorrow.server.quills.manifest import MANIFEST, ORIGIN, Manifest, QuillError

TEMPLATE = Path(__file__).resolve().parent.parent.parent / "quill_template"
# Stored without their dots, so the package keeps them; restored on copy.
DOTTED = {"gitignore": ".gitignore", "github": ".github", "gitkeep": ".gitkeep", "claude": ".claude"}
# The template's example Quill: not for a Quill that has its own.
EXAMPLE = {"quill.toml", "quill.py", "datamodels/item.toml", "tests/test_quill.py", "README.md", "CLAUDE.md.head"}
LEFT_OUT = (ORIGIN, ".git", "__pycache__", ".venv", ".pytest_cache")

ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


def _copy_quill(folder: Path, into: Path) -> None:
    shutil.copytree(folder, into, ignore=shutil.ignore_patterns(*LEFT_OUT), dirs_exist_ok=True)


def _fill(text: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def scaffold(into: Path, manifest: Manifest) -> list[str]:
    """Everything the template has that *into* lacks, written in. Returns what was added."""
    values = {"id": manifest.id, "name": manifest.name, "summary": manifest.summary}
    added: list[str] = []
    for source in sorted(TEMPLATE.rglob("*")):
        if source.is_dir() or "__pycache__" in source.parts:
            continue
        relative = source.relative_to(TEMPLATE)
        if str(relative) in EXAMPLE:
            continue
        parts = [DOTTED.get(part, part) for part in relative.parts]
        dest = into.joinpath(*parts)
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(_fill(source.read_text(encoding="utf-8"), values), encoding="utf-8")
        added.append("/".join(parts))
    if not (into / "CLAUDE.md").exists():
        head = (TEMPLATE / "CLAUDE.md.head").read_text(encoding="utf-8")
        (into / "CLAUDE.md").write_text(head + quill_reference(), encoding="utf-8")
        added.append("CLAUDE.md")
    if not (into / "README.md").exists():
        (into / "README.md").write_text(_readme(manifest), encoding="utf-8")
        added.append("README.md")
    tests = into / "tests"
    if not tests.is_dir() or not any(tests.glob("test_*.py")):
        tests.mkdir(exist_ok=True)
        (tests / "test_quill.py").write_text(_test(manifest), encoding="utf-8")
        added.append("tests/test_quill.py")
    return added


def _readme(manifest: Manifest) -> str:
    rows = [("Datamodels", _data_said(manifest))]
    if manifest.screens:
        rows.append(("Screens", ", ".join(s.get("label") or s["id"] for s in manifest.screens)))
    if manifest.actions:
        rows.append(("Actions", "; ".join(a["label"] for a in manifest.actions)))
    if manifest.code:
        rows.append(("Code", f"`{manifest.code}`, in the sandbox, as whoever uses it"))
    table = "\n".join(f"| {k} | {v} |" for k, v in rows)
    return (
        f"# {manifest.name}\n\n{manifest.summary}\n\n"
        "A [Quill](https://github.com/Cloudmorrow/cloudmorrow/blob/main/docs/QUILLS.md) for Cloudmorrow,"
        " made on somebody's own cloud and exported with `cm quill export`.\n\n"
        f"## What it adds to your Cloudmorrow\n\n| | |\n| --- | --- |\n{table}\n\n"
        "## Working on it\n\n```\nuv sync\ncm quill check\ncm quill test\ncm quill test --sandbox\n"
        "cm quill dev --local\n```\n"
    )


def _data_said(manifest: Manifest) -> str:
    parts = []
    if manifest.uses:
        parts.append("uses " + ", ".join(f"`{manifest.plain(m)}`" for m in manifest.uses))
    if manifest.introduces:
        parts.append("introduces " + ", ".join(f"`{manifest.plain(m.id)}`" for m in manifest.introduces))
    return "; ".join(parts) or "none"


def _test(manifest: Manifest) -> str:
    return (
        f'"""{manifest.name}\'s tests: the real record store and gate, on this machine.\n\n'
        "`cm quill test` runs them; `cm quill test --sandbox` runs the same tests with\n"
        'quill.py in the sandbox, as a server runs it.\n"""\n\n'
        "from cloudmorrow.quill.testing import Harness\n\n\n"
        "def test_it_installs():\n"
        '    with Harness(".") as q:\n'
        f'        assert q.manifest.id == "{manifest.id}"\n'
    )


def with_datasets(into: Path, manifest: Manifest, datasets: dict[str, list[dict]]) -> list[str]:
    """Records of the Quill's own datamodels, written in as per-owner datasets:
    `datasets/<name>.toml`, and a `[[datasets]]` table each in the manifest.
    *datasets* is plain datamodel id -> records (fields only). Returns the files."""
    if not datasets:
        return []
    introduced = {manifest.plain(m.id): m for m in manifest.introduces}
    manifest_path = into / MANIFEST
    text = manifest_path.read_text(encoding="utf-8")
    written: list[str] = []
    (into / "datasets").mkdir(exist_ok=True)
    for plain, records in datasets.items():
        model = introduced.get(plain)
        if model is None:
            raise QuillError(f"{plain} is not a datamodel {manifest.id} introduces")
        links = {f.name for f in model.fields if f.kind == "link"}
        stamps = {f.name for f in model.fields if f.stamp_field}
        kept = [
            {k: v for k, v in r.items() if k not in links and k not in stamps and v is not None and v != ""}
            for r in records
        ]
        name = plain.split(".", 1)[-1]
        (into / "datasets" / f"{name}.toml").write_text(tomli_w.dumps({"records": kept}), encoding="utf-8")
        written.append(f"datasets/{name}.toml")
        dataset_id = f"{name}-records"
        if f'id = "{dataset_id}"' not in text:
            text += (
                f'\n[[datasets]]\nid = "{dataset_id}"\nmodel = "{plain}"\nseed = "per-owner"\n'
                f'file = "datasets/{name}.toml"\n'
            )
    manifest_path.write_text(text, encoding="utf-8")
    return written


def export(folder: Path, manifest: Manifest, into: Path, *, datasets: dict[str, list[dict]] | None = None) -> dict:
    """The Quill as a repository would hold it, in *into*: the folder, the template's
    shape around it, and the datasets chosen. Returns what was added."""
    into.mkdir(parents=True, exist_ok=True)
    _copy_quill(folder, into)
    added = scaffold(into, manifest)
    added += with_datasets(into, manifest, datasets or {})
    return {"added": added}


def tarball(folder: Path, name: str) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path in sorted(folder.rglob("*")):
            relative = path.relative_to(folder)
            if any(part in LEFT_OUT for part in relative.parts):
                continue
            if path.is_file():
                archive.add(path, arcname=str(Path(name) / relative))
    return buffer.getvalue()


# -- forking ------------------------------------------------------------------------------------
def fork(folder: Path, manifest: Manifest, new_id: str, into: Path, *, name: str = "") -> Path:
    """A copy of the Quill under *new_id*, in *into*: the id renamed in the manifest, its
    datamodels' ids and links, and the names its code uses. A textual rename, and
    said so: `cm quill check` says what it missed."""
    if not ID_RE.match(new_id):
        raise QuillError("an id is 2 to 32 lowercase letters, digits and _, starting with a letter")
    if new_id == manifest.id:
        raise QuillError(f"it is called {manifest.id} already; a fork needs a new id")
    into.mkdir(parents=True, exist_ok=True)
    _copy_quill(folder, into)
    old = manifest.id
    for path in sorted(into.rglob("*")):
        if not path.is_file() or path.suffix not in (".toml", ".py", ".md"):
            continue
        text = path.read_text(encoding="utf-8")
        changed = text.replace(f'"{old}.', f'"{new_id}.').replace(f"'{old}.", f"'{new_id}.")
        if path.name == MANIFEST:
            changed = re.sub(r'(?m)^id = "' + re.escape(old) + '"', f'id = "{new_id}"', changed, count=1)
            if name:
                changed = re.sub(r'(?m)^name = ".*"', f'name = "{name}"', changed, count=1)
        if changed != text:
            path.write_text(changed, encoding="utf-8")
    return into
