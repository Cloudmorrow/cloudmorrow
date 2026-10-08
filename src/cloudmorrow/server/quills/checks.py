"""What a Quill adds, checked against the datamodels there are, and described.

`_assemble` puts the datamodels together with every Quill's introductions and
extensions; `_check_bindings` checks that each screen, job and dataset points
at fields that are there, of the right kind; `describe` says it all in the
shape the install sheet draws.
"""

from __future__ import annotations

from cloudmorrow.server.datamodels import (
    Datamodel,
    DatamodelError,
)
from cloudmorrow.server.quills.manifest import MADE_AS, SURFACES, Manifest, QuillError
from cloudmorrow.server.records import NEVER_FOR_ASSISTANTS


def _assemble(
    foundation: dict[str, Datamodel], quills: dict[str, Manifest]
) -> tuple[dict[str, Datamodel], dict[str, str]]:
    """The datamodels there are with these Quills: foundation, introduced, extended.

    Returns them and, per Quill, what stops it fitting — a datamodel it needs
    that is not there, a link that goes nowhere, a scope the store cannot keep.
    """
    models = dict(foundation)
    problems: dict[str, str] = {}
    for manifest in quills.values():
        for model in manifest.introduces:
            if model.id in models:
                problems[manifest.id] = f"{model.id} is introduced twice"
            models[model.id] = model
    for manifest in quills.values():
        for model_id, fields in manifest.extends.items():
            if model_id not in models:
                problems.setdefault(manifest.id, f"{manifest.id} extends {model_id}, which is not installed")
                continue
            try:
                models[model_id] = models[model_id].with_extension(manifest.id, fields)
            except DatamodelError as exc:
                problems.setdefault(manifest.id, str(exc))
    for manifest in quills.values():
        for model_id in manifest.models:
            if model_id not in models:
                problems.setdefault(
                    manifest.id,
                    f"{manifest.id} needs the datamodel {model_id}, which is not installed",
                )
    for model in models.values():
        for f in model.fields:
            if f.kind == "link" and f.to not in models:
                owner = (
                    model.source
                    if model.source != "foundation"
                    else next((q.id for q in quills.values() if model.id in q.models), "")
                )
                if owner:
                    problems.setdefault(owner, f"{model.id}.{f.name} links to {f.to}, which is not installed")
        if model.in_space:
            target = models.get(model.get_field(model.in_space).to)
            if target is not None and not target.space:
                owner = (
                    model.source
                    if model.source != "foundation"
                    else next((q.id for q in quills.values() if model.id in q.models), "")
                )
                if owner:
                    problems.setdefault(owner, f"{model.id} is in_space {target.id}, which is not a space")
    return models, problems


def _check_bindings(manifest: Manifest, models: dict[str, Datamodel]) -> None:
    """Every screen, job and dataset points at fields that are there, of the right kind."""
    where = manifest.id
    mine = manifest.models

    def model_of(thing: str, model_id: str) -> Datamodel:
        if model_id not in mine:
            raise QuillError(f"{where}: {thing} uses {model_id}, which the Quill does not declare in [uses]")
        return models[model_id]

    def need(model: Datamodel, thing: str, name: object, kinds: tuple[str, ...] = ()) -> None:
        if not isinstance(name, str) or name not in model.by_name:
            raise QuillError(f"{where}: {thing} names {name!r}, which {model.id} does not have")
        if kinds and model.by_name[name].kind not in kinds:
            raise QuillError(
                f"{where}: {thing} {name!r} is a {model.by_name[name].kind}; it wants {' or '.join(kinds)}"
            )

    for screen in manifest.screens:
        thing = f"screen {screen['id']!r}"
        if screen["kit"] == "view":
            if screen.get("model"):
                model_of(thing, screen["model"])
            continue
        model = model_of(thing, screen["model"])
        kit = screen["kit"]
        need(model, thing, screen.get("title", model.title))
        if kit == "board":
            need(model, thing + " lane", screen.get("lane"), ("enum", "link"))
            lane = model.by_name[screen["lane"]]
            if lane.kind == "link":
                _check_link_lanes(where, thing, screen, lane, model_of(thing + " lane", lane.to), need)
            elif screen.get("done") and screen["done"] not in lane.values:
                raise QuillError(f"{where}: {thing} done lane {screen['done']!r} is not a value of {lane.name}")
            if screen.get("group"):
                need(model, thing + " group", screen["group"], ("link",))
            if screen.get("body"):
                need(model, thing + " body", screen["body"], ("markdown", "text"))
            # Said under a card's title: a field, or a list of them — a deal's
            # organisation and what it is worth.
            subtitle = screen.get("subtitle")
            for name in [subtitle] if isinstance(subtitle, str) else (subtitle or []):
                need(model, thing + " subtitle", name)
            if not model.ordered or screen["lane"] not in model.ordered_within:
                raise QuillError(f"{where}: {thing} is a board, so {model.id} keeps order within its lanes")
        elif kit == "list":
            if screen.get("tick"):
                need(model, thing + " tick", screen["tick"], ("bool",))
            if screen.get("subtitle"):
                need(model, thing + " subtitle", screen["subtitle"])
            _check_list_groups(where, thing, model, screen, need)
            for name in screen.get("fields", []):
                need(model, thing, name)
        elif kit in ("detail", "form"):
            for name in screen.get("fields", []):
                need(model, thing, name)
        elif kit == "calendar":
            _check_calendar(screen, model, models, thing, need, where)
        elif kit == "editor":
            # A page of text with a title; `path`, when bound, is a string
            # like `folder/sub/title` whose folders are the tree beside it.
            # `where` is the filters every listing is made with — a file's
            # share, and the folder the pages are under — and `suffix` says
            # which files are pages, and what a new one is called.
            need(model, thing + " body", screen.get("body"), ("markdown", "text"))
            if screen.get("path"):
                need(model, thing + " path", screen["path"], ("string",))
            filters = screen.get("where", {})
            if not isinstance(filters, dict) or not all(
                isinstance(k, str) and isinstance(v, (str, int, bool)) for k, v in filters.items()
            ):
                raise QuillError(
                    f'{where}: {thing} where is a table of filters: where = {{ share = "my-files", within = "Notes" }}'
                )
            suffix = screen.get("suffix", "")
            if not isinstance(suffix, str) or (suffix and not suffix.startswith(".")):
                raise QuillError(f'{where}: {thing} suffix is a file suffix, like ".md"')
        elif kit == "grid":
            # Files: folders and tiles, in groups (the shares) picked first.
            if not model.backend:
                raise QuillError(f"{where}: {thing} is a grid, which shows files; {model.id} keeps no bytes")
            need(model, thing + " group", screen.get("group"), ("link",))
            need(model, thing + " folder", screen.get("folder"), ("string",))
            need(model, thing + " kind", screen.get("kind"), ("enum",))
            if "folder" not in model.by_name[screen["kind"]].values:
                raise QuillError(f"{where}: {thing} kind {screen['kind']!r} has no value 'folder'")
            for binding, kinds in (("size", ("int",)), ("modified", ("datetime", "date")), ("mime", ("string",))):
                if screen.get(binding):
                    need(model, f"{thing} {binding}", screen[binding], kinds)
            group_model = models.get(model.by_name[screen["group"]].to)
            if group_model is not None:
                if screen.get("group_subtitle"):
                    need(group_model, thing + " group_subtitle", screen["group_subtitle"])
                if screen.get("group_open"):
                    need(group_model, thing + " group_open", screen["group_open"], ("bool",))
        elif kit == "thread":
            _check_thread(manifest, screen, model, models, need)
    for job in manifest.jobs:
        if job["action"] == "expire":
            model = model_of(f"job {job['id']!r}", job["model"])
            need(model, f"job {job['id']!r}", job["field"], ("datetime", "date"))
            if not model.by_name[job["field"]].indexed:
                raise QuillError(f"{where}: job {job['id']!r} expires on {job['field']}, which must be indexed")
    for hook in manifest.webhooks:
        if hook.get("model"):
            model = model_of(f"webhook {hook['id']!r}", hook["model"])
            for name in hook.get("map", {}):
                need(model, f"webhook {hook['id']!r} map", name)
    for action in manifest.actions:
        thing = f"action {action['id']!r}"
        if action.get("on"):
            model_of(thing, action["on"])
        for spec in action["fields"]:
            if spec["kind"] == "link":
                model_of(f"{thing} field {spec['name']!r}", spec["to"])
    for hook in manifest.hooks:
        model = model_of(f"hook {hook['id']!r}", hook["on"])
        for name in hook.get("fields", []):
            need(model, f"hook {hook['id']!r} fields", name)
    for dataset in manifest.datasets:
        model = model_of(f"dataset {dataset['id']!r}", dataset["model"])
        for record in dataset["records"]:
            for name in record:
                need(model, f"dataset {dataset['id']!r}", name)
        if dataset["seed"] == "per-space":
            # Once in every space that has none: the stages of each new book.
            if not model.in_space:
                raise QuillError(f"{where}: dataset {dataset['id']!r} is seeded per space, and {model.id} is in none")
            if dataset.get("scope"):
                raise QuillError(f"{where}: dataset {dataset['id']!r} is in a space, which has the scope")


def _check_link_lanes(where: str, thing: str, screen: dict, lane, lanes: Datamodel, need) -> None:
    """A board whose lanes are records: a pipeline's stages, which people add to.

    The lanes are the records of the datamodel the lane field links to, in
    their order — so that datamodel keeps one — and, on a board with groups,
    only the ones that link to the group on screen. `done` is then not a
    value but what the finished lane's record says: `{ outcome = "won" }`.
    """
    if not lanes.ordered:
        raise QuillError(
            f"{where}: {thing} lanes are {lanes.id} records, so {lanes.id} keeps an order (ordered_within)"
        )
    done = screen.get("done")
    if done is None:
        return
    if not isinstance(done, dict) or not done:
        raise QuillError(
            f"{where}: {thing} lanes are {lanes.id} records, so done says what the finished one"
            " has: done = { field = value }"
        )
    for name in done:
        need(lanes, thing + " done", name)


def _check_list_groups(where: str, thing: str, model: Datamodel, screen: dict, need) -> None:
    """A list's `group` and `subgroup`: the two levels it is picked through.

    Each is a field whose values sort the records — a link (the linked
    records are the choices), an enum (its values are) or an indexed string
    (the values the records have are, and a new one is a name typed in).
    """
    for level in ("group", "subgroup"):
        name = screen.get(level)
        if not name:
            continue
        need(model, f"{thing} {level}", name, ("link", "enum", "string"))
        field = model.by_name[name]
        if field.kind != "link" and not field.indexed:
            raise QuillError(f"{where}: {thing} {level} {name!r} must be indexed, to be picked by")
    if screen.get("subgroup") and not screen.get("group"):
        raise QuillError(f"{where}: {thing} has a subgroup, so it needs a group above it")
    if screen.get("subgroup") and screen.get("subgroup") == screen.get("group"):
        raise QuillError(f"{where}: {thing} group and subgroup are two different fields")


def _surfaces(manifest: Manifest) -> list[str]:
    """Where its screens are drawn: everywhere, but to an assistant only what one may reach."""
    if not manifest.screens:
        return []
    if all(screen["model"] in NEVER_FOR_ASSISTANTS for screen in manifest.screens):
        return [s for s in SURFACES if s != "assistant"]
    return list(SURFACES)


def _check_thread(manifest: Manifest, screen: dict, model: Datamodel, models: dict, need) -> None:
    """A thread: things written (`body`) in a space (`space`), and how spaces are made.

    `space` is the link field that puts a record in its space, `about` a field
    of the space shown under its name, and `made_as` the fields a space gets
    for how it is made: `public`, `shared` or `personal` — its scope — or
    `direct`, a shared space found-or-made between the people picked, named
    for whoever else is in it.
    """
    where = manifest.id
    thing = f"screen {screen['id']!r}"
    need(model, thing + " space", screen.get("space"), ("link",))
    if model.in_space != screen["space"]:
        raise QuillError(f"{where}: {thing} space {screen['space']!r} is not what {model.id} is in")
    need(model, thing + " body", screen.get("body"), ("text", "markdown", "string"))
    space_model = models[model.by_name[screen["space"]].to]
    if screen.get("about"):
        need(space_model, thing + " about", screen["about"])
    made_as = screen.get("made_as") or {}
    if not isinstance(made_as, dict):
        raise QuillError(f"{where}: {thing} made_as is a table of how a space is made")
    for how, fields in made_as.items():
        if how not in MADE_AS:
            raise QuillError(f"{where}: {thing} made_as {how!r} is one of {', '.join(MADE_AS)}")
        scope = "shared" if how == "direct" else how
        if scope not in space_model.scopes:
            raise QuillError(f"{where}: {thing} made_as {how}, but a {space_model.id} is never {scope}")
        if not isinstance(fields, dict):
            raise QuillError(f"{where}: {thing} made_as {how} is the fields it sets")
        for name, value in fields.items():
            need(space_model, f"{thing} made_as {how}", name)
            f = space_model.by_name[name]
            if f.kind == "enum" and value not in f.values:
                raise QuillError(f"{where}: {thing} made_as {how}: {value!r} is not a value of {name}")
            if how == "direct" and not f.indexed:
                raise QuillError(f"{where}: {thing} made_as direct marks a space by {name}, which must be indexed")


def _check_calendar(screen: dict, model: Datamodel, models: dict[str, Datamodel], thing: str, need, where: str) -> None:
    """A calendar: two moments, whether it is all day, and the spaces it is drawn from."""
    moments = ("datetime", "date")
    need(model, thing + " starts", screen.get("starts"), moments)
    need(model, thing + " ends", screen.get("ends"), moments)
    for name in ("starts", "ends"):
        if not model.by_name[screen[name]].indexed:
            raise QuillError(f"{where}: {thing} {name} {screen[name]!r} must be indexed, to ask for a range of days")
    if screen.get("all_day"):
        need(model, thing + " all_day", screen["all_day"], ("bool",))
    need(model, thing + " space", screen.get("space"), ("link",))
    space = models.get(model.by_name[screen["space"]].to)
    if space is None or not space.space:
        raise QuillError(f"{where}: {thing} space {screen['space']!r} must link to a space")
    if screen.get("colour"):
        need(space, thing + " colour", screen["colour"], ("string", "enum"))
    if screen.get("subtitle"):
        need(model, thing + " subtitle", screen["subtitle"])


def runs_code(manifest: Manifest) -> list[str]:
    """Every command a Quill would have this server run, as a person reads one."""
    return list(dict.fromkeys(" ".join(s["command"]) for s in manifest.services))


def code_summary(manifest: Manifest) -> dict:
    """What its Python does, for the install sheet: nothing of it runs to find out."""
    if not manifest.code:
        return {}
    return {
        "sandboxed": True,
        "views": [s["label"] for s in manifest.screens if s["kit"] == "view"],
        "actions": [a["label"] for a in manifest.actions],
        "hooks": [f"when a {h['on']} is {' or '.join(h['when'])}" for h in manifest.hooks],
        "jobs": [f"{j['id']} every {j['every']}" for j in manifest.jobs if j["action"] == "call"],
        "fetch": [{"host": f["host"], "why": f["why"]} for f in manifest.fetch],
        "secrets": [{"key": s["key"], "why": s["why"]} for s in manifest.secrets],
        "machine": [
            {
                "id": m["id"],
                "why": m["why"],
                "every": m.get("every", ""),
                "folders": [f"{f['name']} ({f['access']})" for f in m["folders"]],
                "run": list(m["run"]),
            }
            for m in manifest.machine
        ],
    }


def describe(
    manifest: Manifest,
    models: dict[str, Datamodel],
    *,
    new_foundation: list[str] | None = None,
    installed: Manifest | None = None,
) -> dict:
    """What a Quill is and adds, in the shape the install sheet and the catalog draw."""
    introduced = {m.id for m in manifest.introduces}
    data = []
    for model_id in sorted(manifest.models):
        model = models.get(model_id)
        if model_id in introduced:
            how = "introduces"
        elif model_id in manifest.extends:
            how = "extends"
        elif any(g["model"] == model_id for g in manifest.grants):
            how = "asks for"
        else:
            how = "uses"
        row = {
            "id": model_id,
            "label": model.label if model else model_id,
            "how": how,
            "foundation": bool(model and model.source == "foundation"),
            "new": model_id in (new_foundation or []) or model_id in introduced,
        }
        if model_id in manifest.extends:
            row["fields"] = [f"{manifest.id}.{name}" for name in manifest.extends[model_id]]
        grant = next((g for g in manifest.grants if g["model"] == model_id), None)
        if grant:
            row["access"] = grant["access"]
            row["why"] = grant["why"]
        data.append(row)
    body = manifest.to_dict()
    body.update(
        {
            "readme": manifest.readme,
            "data": data,
            "surfaces": _surfaces(manifest),
            "installed_version": installed.version if installed else None,
            # What it runs on this server, as whom, and what it may reach
            # there: what an administrator says yes to (see quills.services).
            # Who it runs as is known once it is installed; before, it is
            # whoever says yes, and the sheet says that.
            "runs_code": runs_code(manifest),
            "quill_code": code_summary(manifest),
            "runs_as": manifest.origin.get("installed_by", "") if installed else "",
            "reach": sorted(manifest.models),
        }
    )
    return body
