"""`cloudmorrow update`: what the server offers, and where `update server` ssh's to."""

from __future__ import annotations

from pathlib import Path

import cloudmorrow
from cloudmorrow.cli.update import _deploy_lines, dev_checkout, ssh_target
from cloudmorrow.client.config import ClientConfig


def test_client_release_describes_what_to_install(client):
    payload = client.get("/api/client").json()
    assert payload["version"] == cloudmorrow.__version__
    # Nothing published yet, so the fallback spec is what a machine would get.
    assert payload["package"] == "cloudmorrow[tui,agent]"
    assert payload["wheel"] == ""


def test_client_release_prefers_a_published_wheel(client, config):
    wheel = config.dist_dir / "cloudmorrow-0.1.0-py3-none-any.whl"
    wheel.parent.mkdir(parents=True, exist_ok=True)
    wheel.write_bytes(b"not really a wheel, but it is the newest one")
    payload = client.get("/api/client").json()
    assert payload["wheel"] == wheel.name
    assert payload["package"].startswith("cloudmorrow[tui,agent] @ http://")
    assert payload["package"].endswith(f"/dist/{wheel.name}")


def test_client_release_needs_no_auth(client):
    """Same reason /install.sh needs none: this is how a machine gets the code."""
    assert client.get("/api/client").status_code == 200


def test_ssh_target_defaults_to_the_api_host():
    config = ClientConfig(api_url="https://cm.hl.bramlabs.io")
    assert ssh_target(config) == "cm.hl.bramlabs.io"


def test_ssh_target_can_be_an_ssh_alias():
    config = ClientConfig(api_url="https://cm.hl.bramlabs.io", server_host="homelab")
    assert ssh_target(config) == "homelab"


def test_ssh_target_ignores_the_port():
    config = ClientConfig(api_url="http://192.168.1.10:8787")
    assert ssh_target(config) == "192.168.1.10"


def test_a_development_checkout_is_recognised():
    """Running from this repo, update must not pip over the checkout."""
    found = dev_checkout()
    assert found == Path(cloudmorrow.__file__).resolve().parents[2]
    assert (found / ".git").is_dir()


def test_server_host_round_trips_through_the_config(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDMORROW_CONFIG_DIR", str(tmp_path))
    config = ClientConfig.load()
    config.server_host = "homelab"
    config.save()
    assert ClientConfig.load().server_host == "homelab"


# -- what `update server` tells you afterwards ------------------------------
def _result(**overrides) -> dict:
    result = {
        "source": "/opt/cloudmorrow/src",
        "branch": "main",
        "old_commit": "a" * 40,
        "new_commit": "b" * 40,
        "commit_subject": "bbbbbbb a real commit",
        "changed_files": 2,
        "changed": True,
        "reinstalled": True,
        "published_wheel": "cloudmorrow-0.1.0-py3-none-any.whl",
        "restarting": True,
        "restart_blocked": "",
    }
    result.update(overrides)
    return result


def test_a_deploy_reports_the_restart_and_waits_for_it():
    lines, waiting = _deploy_lines(_result(), restart=True, force=False)
    assert waiting is True
    assert any("Updated" in line for line in lines)
    assert any("published" in line for line in lines)


def test_a_forced_redeploy_of_the_same_commit_still_says_it_is_restarting():
    """--force restarts onto the commit already deployed. Saying only
    "already up to date" while the API bounces underneath you hides that."""
    lines, waiting = _deploy_lines(
        _result(changed=False, new_commit="a" * 40, changed_files=0),
        restart=True,
        force=True,
    )
    assert waiting is True
    assert any("Already up to date" in line for line in lines)


def test_nothing_new_and_no_force_waits_for_nothing():
    lines, waiting = _deploy_lines(
        _result(changed=False, new_commit="a" * 40, reinstalled=False,
                published_wheel="", restarting=False),
        restart=True,
        force=False,
    )
    assert waiting is False
    assert not any("not restarted" in line for line in lines)


def test_a_blocked_restart_is_said_out_loud_and_not_waited_for():
    lines, waiting = _deploy_lines(
        _result(restarting=False, restart_blocked="cloudmorrow.service has Restart=on-failure"),
        restart=True,
        force=False,
    )
    assert waiting is False
    assert any("Not restarted" in line for line in lines)
    assert any("old code is still serving" in line for line in lines)


def test_no_restart_says_so_only_when_there_was_something_to_restart_for():
    lines, waiting = _deploy_lines(
        _result(restarting=False), restart=False, force=False
    )
    assert waiting is False
    assert any("not restarted, as asked" in line for line in lines)


def _installed(tmp_path, *tools: str):
    """A venv-shaped prefix with these commands in its bin, and a bin dir on the PATH."""
    prefix = tmp_path / "venv"
    (prefix / "bin").mkdir(parents=True)
    for tool in tools:
        (prefix / "bin" / tool).write_text("#!/bin/sh\n")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    return prefix, bindir


def test_an_update_links_a_command_that_is_new_beside_the_old_one(tmp_path):
    from cloudmorrow.links import link_new_commands

    prefix, bindir = _installed(tmp_path, "cloudmorrow", "cm", "cloudmorrow-agent")
    (bindir / "cloudmorrow").symlink_to(prefix / "bin" / "cloudmorrow")
    (bindir / "cloudmorrow-agent").symlink_to(prefix / "bin" / "cloudmorrow-agent")

    linked = link_new_commands(prefix, which=lambda _: str(bindir / "cloudmorrow"))

    assert linked == [bindir / "cm"]
    assert (bindir / "cm").resolve() == (prefix / "bin" / "cm").resolve()
    # The ones that were there are still the same links.
    assert (bindir / "cloudmorrow").resolve() == (prefix / "bin" / "cloudmorrow").resolve()


def test_an_update_leaves_a_cm_that_is_somebody_elses_alone(tmp_path):
    from cloudmorrow.links import link_new_commands

    prefix, bindir = _installed(tmp_path, "cloudmorrow", "cm")
    (bindir / "cloudmorrow").symlink_to(prefix / "bin" / "cloudmorrow")
    (bindir / "cm").write_text("#!/bin/sh\necho somebody else's cm\n")

    assert link_new_commands(prefix, which=lambda _: str(bindir / "cloudmorrow")) == []
    assert (bindir / "cm").read_text() == "#!/bin/sh\necho somebody else's cm\n"


def test_an_update_links_nothing_when_cloudmorrow_is_not_our_link(tmp_path):
    from cloudmorrow.links import link_new_commands

    prefix, bindir = _installed(tmp_path, "cloudmorrow", "cm")
    # pipx, or a checkout: `cloudmorrow` on the PATH is a real file, not our link.
    (bindir / "cloudmorrow").write_text("#!/bin/sh\n")

    assert link_new_commands(prefix, which=lambda _: str(bindir / "cloudmorrow")) == []
    assert not (bindir / "cm").exists()
    assert link_new_commands(prefix, which=lambda _: None) == []


def test_the_first_run_after_an_update_links_its_own_commands(tmp_path, monkeypatch):
    """The old updater installed the new wheel; the new code must finish the job."""
    from cloudmorrow import links

    prefix, bindir = _installed(tmp_path, "cloudmorrow", "cm")
    (bindir / "cloudmorrow").symlink_to(prefix / "bin" / "cloudmorrow")
    monkeypatch.setattr(links.sys, "executable", str(prefix / "bin" / "python"))
    monkeypatch.setattr(links.shutil, "which", lambda _: str(bindir / "cloudmorrow"))

    assert links.ensure_commands_linked() == [bindir / "cm"]
    assert (bindir / "cm").resolve() == (prefix / "bin" / "cm").resolve()
    # Done once; the next run finds nothing to do.
    assert links.ensure_commands_linked() == []


def test_a_first_run_that_cannot_link_says_nothing_and_carries_on(tmp_path, monkeypatch):
    from cloudmorrow import links

    prefix, bindir = _installed(tmp_path, "cloudmorrow", "cm")
    (bindir / "cloudmorrow").symlink_to(prefix / "bin" / "cloudmorrow")
    monkeypatch.setattr(links.sys, "executable", str(prefix / "bin" / "python"))
    monkeypatch.setattr(links.shutil, "which", lambda _: str(bindir / "cloudmorrow"))

    def refuse(self, target):
        raise PermissionError("read-only")

    monkeypatch.setattr(links.Path, "symlink_to", refuse)
    assert links.ensure_commands_linked() == []


def test_the_same_version_as_the_server_is_nothing_to_update():
    from cloudmorrow.cli.update import needs_update

    assert needs_update("0.9.0", "0.9.0") is False
    assert needs_update("0.9.0", "0.10.0") is True
    # A server that does not say is not trusted to be the same.
    assert needs_update("0.9.0", "") is True


def test_an_update_says_what_it_went_from_and_to():
    from cloudmorrow.cli.update import updated_line

    line = updated_line("0.9.0", "0.10.0")
    assert "updated" in line and "v0.9.0" in line and "v0.10.0" in line
    assert "reinstalled" in updated_line("0.9.0", "0.9.0")


# -- `update all`: the server, and then this machine ------------------------
def test_update_all_deploys_the_server_before_installing_here(monkeypatch):
    """The wheel is built by the deploy, so the deploy has to go first."""
    from typer.testing import CliRunner

    from cloudmorrow.cli import update as update_cli

    order: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        update_cli, "update_server", lambda **kwargs: order.append(("server", kwargs))
    )
    monkeypatch.setattr(
        update_cli, "_update_client", lambda **kwargs: order.append(("client", kwargs))
    )

    result = CliRunner().invoke(update_cli.app, ["all", "--branch", "main", "--no-agent"])

    assert result.exit_code == 0, result.output
    assert [what for what, _ in order] == ["server", "client"]
    assert order[0][1] == {
        "ssh": False,
        "host": None,
        "branch": "main",
        "force": False,
        "restart": True,
        "wait": 60,
    }
    assert order[1][1] == {"check": False, "agent": False, "force": False}


def test_update_all_installs_nothing_here_when_the_deploy_fails(monkeypatch):
    import typer
    from typer.testing import CliRunner

    from cloudmorrow.cli import update as update_cli

    installed: list[dict] = []

    def explode(**_kwargs):
        raise typer.Exit(code=1)

    monkeypatch.setattr(update_cli, "update_server", explode)
    monkeypatch.setattr(update_cli, "_update_client", lambda **kwargs: installed.append(kwargs))

    result = CliRunner().invoke(update_cli.app, ["all"])

    assert result.exit_code == 1
    assert installed == []
