"""The icon library: its files are sound, it is served, and a Quill is told when it names nothing."""

from __future__ import annotations

from typer.testing import CliRunner

from cloudmorrow import icons
from cloudmorrow.cli import quill as quill_cli
from tests.conftest import QUILL_CATALOG

DATAMODELS = QUILL_CATALOG / "datamodels"
runner = CliRunner()


def test_the_shipped_library_checks_out():
    assert icons.check() == []
    found = icons.icons()
    assert len(found) >= 90 and {t["id"] for t in icons.themes()} >= {"animals", "office", "it"}
    for icon in found.values():
        assert icon.size in icons.SIZES and all(len(row) == icon.size for row in icon.rows)
        assert icon.theme and icon.name and icon.tags
    hedgehog = icons.get("hedgehog")
    assert hedgehog is not None and hedgehog.theme == "animals" and "morrow" in hedgehog.tags
    assert icons.get("no-such-icon") is None


def test_svg_draws_dots_the_way_the_web_app_does():
    out = icons.svg(["X.", ".X"])
    assert out.startswith('<svg class="pixel-icon" viewBox="0 0 2 2" fill="currentColor" aria-hidden="true">')
    assert out.count("<rect") == 2
    assert '<rect x="0.08" y="0.08" width="0.84" height="0.84" rx="0.16"/>' in out
    assert '<rect x="1.08" y="1.08"' in out
    assert icons.svg(["....", "....", "....", "...."]).count("<rect") == 0


def test_check_names_what_is_wrong(tmp_path, monkeypatch):
    monkeypatch.setattr(icons, "HERE", tmp_path)
    (tmp_path / "themes.toml").write_text(
        '[[themes]]\nid = "t"\nname = "T"\ndescription = "d"\nfile = "t.toml"\n'
        '[[themes]]\nid = "gone"\nname = "Gone"\ndescription = "d"\nfile = "gone.toml"\n'
    )
    (tmp_path / "t.toml").write_text(
        '[[icons]]\nid = "ok"\nname = "Ok"\ntags = ["a"]\nrows = ["X.", ".X"]\n'
        '[[icons]]\nid = "Bad Id"\nname = "Bad"\ntags = ["a"]\nrows = ["XX", "X"]\n'
        '[[icons]]\nid = "ok"\nname = "Twice"\ntags = ["a"]\nrows = ["..", ".."]\n'
        '[[icons]]\nid = "odd"\nname = "Odd"\ntags = []\nrows = ["XO", "XX"]\n'
    )
    (tmp_path / "stray.toml").write_text("")
    problems = "\n".join(icons.check())
    for said in (
        "stray.toml is not in themes.toml",
        "gone.toml is missing",
        "an id is lowercase",
        "2 rows; an icon is 12×12 or 8×8",
        "already in t.toml",
        "nothing is drawn",
        "no tags",
        "rows are X and . only",
    ):
        assert said in problems, said


def test_the_library_is_served_to_anybody(client):
    r = client.get("/icons.json")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=3600"
    data = r.json()
    assert [t["id"] for t in data["themes"]][:3] == ["animals", "office", "it"]
    assert set(data["icons"]) == set(icons.icons())
    assert data["icons"]["hedgehog"]["rows"] == list(icons.get("hedgehog").rows)
    assert data["icons"]["hedgehog"]["theme"] == "animals"


def test_a_quill_is_told_when_its_icon_is_nowhere(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(quill_cli.app, ["new", "plants"])
    manifest = tmp_path / "quill-plants" / "quill.toml"
    checked = runner.invoke(quill_cli.app, ["check", str(manifest.parent), "--datamodels", str(DATAMODELS)])
    assert checked.exit_code == 0, checked.output
    assert "icon 'plants' is not in the icon library" in checked.output
    manifest.write_text(manifest.read_text().replace('icon = "plants"', 'icon = "hedgehog"'))
    checked = runner.invoke(quill_cli.app, ["check", str(manifest.parent), "--datamodels", str(DATAMODELS)])
    assert checked.exit_code == 0 and "not in the icon library" not in checked.output
    manifest.write_text(manifest.read_text().replace('icon = "hedgehog"', 'icon = "tasks"'))
    checked = runner.invoke(quill_cli.app, ["check", str(manifest.parent), "--datamodels", str(DATAMODELS)])
    assert "not in the icon library" not in checked.output
