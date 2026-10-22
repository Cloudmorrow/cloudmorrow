"""The words of a list of projects: a `list` screen that binds `vault`.

    cm devproject init [name] [--path DIR]     # this folder: a project, its .env files into its vault
    cm devproject update [project] [--path DIR] [--force]   # git pull, then the .env files from the vault
    cm devproject clone <project> [DIR]        # on another machine: the repository, then its .env files
    cm devproject secrets [project]            # its environments, and how many keys each
    cm devproject secrets import [project] [-e local] [-f .env]
    cm devproject secrets export [project] [-e local] [-f .env] [--force]

A project is named by its name, its vault or the start of its id; named
nowhere, it is the one the folder (`--path`, else here) is a checkout of.
Without `-e` and `-f`, `secrets import` and `export` do every file and every
environment; with only `-f`, the file says which environment it is. The
folder and the files are cloudmorrow/checkout.py's.
"""

from __future__ import annotations

import json
from pathlib import Path

from rich.markup import escape

from cloudmorrow.checkout import (
    CheckoutError,
    Imported,
    Projects,
    Written,
    clone,
    env_files,
    environment_of,
    export_file,
    file_for,
    import_file,
    init,
    pull,
    remembered,
    remote,
    write_all,
)

# quillrun.out, .console and .emit, looked up as they print: see screen.py.
from cloudmorrow.cli import quillrun
from cloudmorrow.cli.common import fail, plural, warn_if_tracked
from cloudmorrow.cli.quillrun.screen import Screen, _find
from cloudmorrow.cli.secret import print_import
from cloudmorrow.client.api import CloudmorrowClient

WORDS = ("init", "update", "clone", "secrets")


def _folder(path: str) -> Path:
    return Path(path or ".").expanduser().resolve()


async def _project(api: CloudmorrowClient, projects: Projects, key: str, path: str) -> tuple[dict, Path]:
    """The project named, or the one the folder is; and the folder it is in on this machine."""
    records = await api.records(projects.model)
    server = api.config.api_url
    if key:
        by_vault = [r for r in records if projects.vault_of(r) == key.lower()]
        record = by_vault[0] if len(by_vault) == 1 else _find(records, key, projects.title)
        folder = _folder(path) if path else remembered(server, projects.vault_of(record)) or _folder("")
        return record, folder
    folder = _folder(path)
    record = projects.here(records, folder, server)
    if record is None:
        fail(f"{folder} is not a project yet: `init` makes it one, or name the project")
    return record, folder


def _said_written(written: list[Written], folder: Path) -> None:
    if not written:
        quillrun.console.print("    [dim]no secrets in its vault yet[/]")
    for one in written:
        if one.state == "written":
            changed = f"  [dim]{', '.join(one.changed)}[/]" if one.changed else ""
            quillrun.console.print(f"    [green]wrote[/]     {one.file:<16} [dim]{one.environment}[/]{changed}")
            warn_if_tracked(folder / one.file)
        elif one.state == "unchanged":
            quillrun.console.print(f"    [dim]unchanged {one.file:<16} {one.environment}[/]")
        else:
            quillrun.console.print(
                f"    [yellow]kept[/]      {one.file:<16} [dim]{one.environment}: only the file has[/] "
                f"{', '.join(one.only_here)}"
            )
    if any(one.state == "kept" for one in written):
        quillrun.console.print(
            "[dim]A kept file has keys the vault does not: `secrets import` them, or --force to write it anyway.[/]"
        )


def _said_imported(done: list[Imported]) -> None:
    if not done:
        quillrun.console.print("    [dim]no .env files here[/]")
    for one in done:
        quillrun.console.print(f"  [b]{escape(one.file)}[/] [dim]→ {one.environment}[/]")
        print_import(one.result)


async def _act_projects(
    api: CloudmorrowClient,
    screen: Screen,
    action: str,
    args: list[str],
    local: dict,
) -> None:
    projects = Projects.of(screen.spec, screen.models)
    if projects is None:
        fail(f"{action} is for a list of projects; {screen.quill['id']} binds no vault")
    word = f"cm {screen.quill['id']}"
    path, environment, file = local.get("path", ""), local.get("env", ""), local.get("file", "")
    force = bool(local.get("force"))
    try:
        if action == "init":
            if len(args) > 1:
                fail(f"{word} init [name] [--path DIR]")
            folder = _folder(path)
            record, made, done = await init(api, projects, folder, name=args[0] if args else "")
            vault = projects.vault_of(record)
            said = "Made" if made else "Found"
            quillrun.console.print(
                f"[green]{said}[/] [b]{escape(projects.name(record))}[/] [dim]in {folder}, vault {vault}"
                f"{', ' + escape(projects.repo_of(record)) if projects.repo_of(record) else ''}[/]"
            )
            _said_imported(done)
            return

        if action == "update":
            if len(args) > 1:
                fail(f"{word} update [project] [--path DIR] [--force]")
            record, folder = await _project(api, projects, args[0] if args else "", path)
            if not folder.is_dir():
                fail(f"{folder} is not there: `{word} clone {projects.name(record)}` puts it there")
            if remote(folder):
                head = await pull(folder)
                quillrun.console.print(f"[green]Pulled[/] [b]{escape(projects.name(record))}[/] [dim]{escape(head)}[/]")
            else:
                quillrun.console.print(
                    f"[b]{escape(projects.name(record))}[/] [dim]{folder} is no git checkout: only the .env files[/]"
                )
            _said_written(await write_all(api, projects, record, folder, force=force), folder)
            return

        if action == "clone":
            if not args or len(args) > 2:
                fail(f"{word} clone <project> [DIR]")
            records = await api.records(projects.model)
            by_vault = [r for r in records if projects.vault_of(r) == args[0].lower()]
            record = by_vault[0] if len(by_vault) == 1 else _find(records, args[0], projects.title)
            url = projects.repo_of(record)
            if not url:
                fail(f"{projects.name(record)} has no repository: `{word} set {args[0]} {projects.repo}=…`")
            folder = _folder(args[1] if len(args) > 1 else path or projects.vault_of(record))
            await clone(url, folder)
            quillrun.console.print(f"[green]Cloned[/] [b]{escape(projects.name(record))}[/] [dim]into {folder}[/]")
            _said_written(await write_all(api, projects, record, folder, force=force), folder)
            return

        # secrets [import|export] [project]
        verb = args[0] if args and args[0] in ("import", "export", "list") else "list"
        rest = args[1:] if args and args[0] in ("import", "export", "list") else args
        if len(rest) > 1:
            fail(f"{word} secrets [import|export] [project] [-e ENV] [-f FILE]")
        record, folder = await _project(api, projects, rest[0] if rest else "", path)
        vault = projects.vault_of(record)
        files = projects.files_of(record)
        if verb == "list":
            found = await api.secret_environments(vault=vault)
            if local.get("plain"):
                quillrun.emit(json.dumps({"vault": vault, "environments": found, "files": files}, indent=2) + "\n")
                return
            quillrun.console.print(f"[b]{escape(projects.name(record))}[/] [dim]vault {vault}[/]")
            if not found:
                quillrun.console.print(f"    [dim]nothing yet: `{word} secrets import` reads the .env files here[/]")
            for one in found:
                name = one["environment"]
                quillrun.console.print(
                    f"    {name:<14} {plural(one['secrets'], 'key'):>8}  [dim]{file_for(name, files)}[/]"
                )
            return
        if verb == "import":
            if file:
                target = folder / file if not Path(file).is_absolute() else Path(file)
                chosen = environment or environment_of(target.name, {p.name for p in target.parent.iterdir()})
                if not chosen:
                    fail(f"which environment is {target.name}? say it with -e")
                pairs = {chosen: target}
            elif environment:
                pairs = {environment: folder / file_for(environment, files)}
            else:
                pairs = {env: folder / name for env, name in env_files(folder).items()}
            missing = [str(p) for p in pairs.values() if not p.is_file()]
            if missing:
                fail(f"no such file: {', '.join(missing)}")
            done = [await import_file(api, vault, env, p) for env, p in pairs.items()]
            # Which file each environment came from, for writing it back.
            if projects.files and done:
                remembered_files = {**files, **{one.environment: one.file for one in done if "/" not in one.file}}
                if remembered_files != files:
                    await api.update_record(projects.model, record["id"], {projects.files: remembered_files})
            quillrun.console.print(f"[dim]into vault[/] [b]{vault}[/]")
            _said_imported(done)
            return
        # export
        if environment or file:
            chosen = environment or environment_of(Path(file).name)
            if not chosen:
                fail(f"which environment goes into {file}? say it with -e")
            target = Path(file) if file and Path(file).is_absolute() else folder / (file or file_for(chosen, files))
            _said_written([await export_file(api, vault, chosen, target, force=force)], target.parent)
            return
        _said_written(await write_all(api, projects, record, folder, force=force), folder)
    except CheckoutError as exc:
        fail(str(exc))
