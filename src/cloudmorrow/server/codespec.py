"""The parts of a manifest that name a Quill's Python: read, checked, never run.

    [quill] code = "quill.py"          the module (or package) the handlers are in
    [[screens]] view = "garage"        a screen a view draws, instead of a kit element
    [[actions]]                        something a person can do, with its form
    [[hooks]]                          code run when a record changes
    [[jobs]] action = "call"           a handler on a clock
    [[webhooks]] handler = …           a webhook answered by code
    [[apis]] handler = …               an API answered by code
    [[fetch]]                          the hosts its code may reach
    [[secrets]]                        the secrets its code may read, by key
    [[machine]]                        code that runs on a person's own machine

Everything a Quill's code may do is here, so the install sheet, `cm quill
check` and the catalog know it without running anything. The handlers
themselves are found by reading the source (`scan_handlers`): a decorator
`@action("log_service")` over a function is a handler called log_service.
A name the manifest uses that the code does not have fails the check.

See docs/QUILLCODE.md.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from cloudmorrow.server.datamodels import DatamodelError, Field, parse_duration, parse_field

HANDLER_KINDS = ("view", "action", "hook", "job", "webhook", "api", "machine")
HOOK_WHEN = ("created", "changed", "deleted")
TONES = ("neutral", "primary", "danger")
FOLDER_ACCESS = ("read", "write")
SDK_MAJOR = "1"

HANDLER_RE = re.compile(r"^[a-z_][a-z0-9_]{0,63}$")
ACTION_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
# A host its code may fetch from: a name, or `*.` and a name for its subdomains.
HOST_RE = re.compile(r"^(\*\.)?([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
FOLDER_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
PROGRAM_RE = re.compile(r"^[A-Za-z0-9._+-]{1,64}$")


class CodeSpecError(ValueError):
    """A part of the manifest about code that does not say something the core can use."""


@dataclass(slots=True)
class CodeSpec:
    code: str = ""
    sdk: str = ""
    actions: tuple[dict, ...] = ()
    hooks: tuple[dict, ...] = ()
    fetch: tuple[dict, ...] = ()
    secrets: tuple[dict, ...] = ()
    machine: tuple[dict, ...] = ()
    # Every handler the manifest names, by kind: what the code must have.
    needs: dict[str, set[str]] = field(default_factory=dict)


def _tables(data: dict, key: str, where: str) -> list[dict]:
    items = data.get(key, [])
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise CodeSpecError(f"{where}: [[{key}]] must be tables")
    return items


def _handler(value: object, where: str, thing: str) -> str:
    if not isinstance(value, str) or not HANDLER_RE.match(value):
        raise CodeSpecError(f"{where}: {thing} handler {value!r} is a Python function name")
    return value


def action_fields(action: dict) -> list[Field]:
    """An action's form, as fields the record store's coercion understands."""
    out = []
    for spec in action.get("fields", []):
        rest = {k: v for k, v in spec.items() if k != "name"}
        out.append(parse_field(f"action {action['id']}", spec["name"], rest))
    return out


def parse_code(
    data: dict,
    folder: Path | None,
    where: str,
    *,
    screens: list[dict],
    jobs: list[dict],
    webhooks: list[dict],
    apis: list[dict],
) -> CodeSpec:
    """The code half of a manifest, checked on its own and normalised in place."""
    head = data.get("quill", {})
    needs: dict[str, set[str]] = {kind: set() for kind in HANDLER_KINDS}

    code = head.get("code", "")
    if not isinstance(code, str):
        raise CodeSpecError(f"{where}: [quill] code is the file its handlers are in, like quill.py")
    sdk = str(head.get("sdk", SDK_MAJOR if code else ""))
    if code and sdk != SDK_MAJOR:
        raise CodeSpecError(
            f"{where}: it is written for SDK {sdk}; this server runs SDK {SDK_MAJOR}"
        )
    if code:
        if not re.match(r"^[a-z_][a-z0-9_]*(\.py)?$", code):
            raise CodeSpecError(f"{where}: code {code!r} is a module in the Quill's folder, like quill.py")
        if folder is not None and not (folder / code).exists():
            raise CodeSpecError(f"{where}: code = {code!r}, and there is no {code} in the Quill")

    for screen in screens:
        if "view" in screen:
            if screen.get("kit") not in (None, "view"):
                raise CodeSpecError(f"{where}: screen {screen.get('id')!r} is a kit element or a view, not both")
            screen["kit"] = "view"
            needs["view"].add(_handler(screen["view"], where, f"screen {screen.get('id')!r}"))

    actions = _tables(data, "actions", where)
    seen: set[str] = set()
    for item in actions:
        action_id = str(item.get("id", ""))
        if not ACTION_RE.match(action_id):
            raise CodeSpecError(f"{where}: every action needs an id of lowercase letters and -")
        if action_id in seen:
            raise CodeSpecError(f"{where}: two actions called {action_id!r}")
        seen.add(action_id)
        thing = f"action {action_id!r}"
        if not str(item.get("label", "")).strip():
            raise CodeSpecError(f"{where}: {thing} needs a label: what the button says")
        item["label"] = str(item["label"]).strip()
        item["handler"] = _handler(item.get("handler", action_id.replace("-", "_")), where, thing)
        needs["action"].add(item["handler"])
        on = item.get("on", "")
        if on and not isinstance(on, str):
            raise CodeSpecError(f"{where}: {thing} on is a datamodel")
        raw = item.get("fields", {})
        if not isinstance(raw, dict):
            raise CodeSpecError(f"{where}: {thing} [actions.fields] is a table of fields")
        parsed = []
        for name, spec in raw.items():
            try:
                parsed.append(parse_field(f"{where} {thing}", name, spec).to_dict())
            except DatamodelError as exc:
                raise CodeSpecError(str(exc)) from exc
        item["fields"] = parsed
        tone = item.get("tone", "neutral")
        if tone not in TONES:
            raise CodeSpecError(f"{where}: {thing} tone is one of {', '.join(TONES)}")
        for key in ("confirm", "description"):
            if key in item and not isinstance(item[key], str):
                raise CodeSpecError(f"{where}: {thing} {key} is words")
        if not isinstance(item.get("assistant", True), bool):
            raise CodeSpecError(f"{where}: {thing} assistant is true or false")

    hooks = _tables(data, "hooks", where)
    for i, item in enumerate(hooks):
        item.setdefault("id", f"hook-{i + 1}")
        thing = f"hook {item['id']!r}"
        if not item.get("on") or not isinstance(item["on"], str):
            raise CodeSpecError(f"{where}: {thing} is on a datamodel: on = \"task\"")
        when = item.get("when", list(HOOK_WHEN))
        when = [when] if isinstance(when, str) else when
        if not isinstance(when, list) or not when or any(w not in HOOK_WHEN for w in when):
            raise CodeSpecError(f"{where}: {thing} when is {', '.join(HOOK_WHEN)}, or a list of them")
        item["when"] = when
        fields = item.get("fields", [])
        if not isinstance(fields, list) or not all(isinstance(f, str) for f in fields):
            raise CodeSpecError(f"{where}: {thing} fields is a list of field names")
        item["handler"] = _handler(item.get("handler"), where, thing)
        needs["hook"].add(item["handler"])

    for job in jobs:
        if job.get("action") == "call":
            thing = f"job {job.get('id')!r}"
            job["handler"] = _handler(job.get("handler"), where, thing)
            if not job.get("every"):
                raise CodeSpecError(f"{where}: {thing} calls its handler every so often: every = \"1h\"")
            needs["job"].add(job["handler"])

    for hook in webhooks:
        if hook.get("handler"):
            needs["webhook"].add(_handler(hook["handler"], where, f"webhook {hook.get('id')!r}"))
    for api in apis:
        if api.get("handler"):
            needs["api"].add(_handler(api["handler"], where, f"api {api.get('id')!r}"))

    fetch = _tables(data, "fetch", where)
    for item in fetch:
        host = str(item.get("host", "")).lower()
        if not HOST_RE.match(host):
            raise CodeSpecError(f"{where}: fetch host {host!r} is a name like api.example.com, or *.example.com")
        if not str(item.get("why", "")).strip():
            raise CodeSpecError(f"{where}: fetch {host} says why; a person reads it")
        item["host"] = host

    secrets = _tables(data, "secrets", where)
    for item in secrets:
        key = str(item.get("key", ""))
        if not KEY_RE.match(key):
            raise CodeSpecError(f"{where}: a secret's key is like TRACKER_API_KEY")
        if not str(item.get("why", "")).strip():
            raise CodeSpecError(f"{where}: the secret {key} says why; a person reads it")

    machine = _tables(data, "machine", where)
    seen = set()
    for item in machine:
        machine_id = str(item.get("id", ""))
        if not ACTION_RE.match(machine_id) or machine_id in seen:
            raise CodeSpecError(f"{where}: every [[machine]] needs its own id of lowercase letters and -")
        seen.add(machine_id)
        thing = f"machine {machine_id!r}"
        item["handler"] = _handler(item.get("handler", machine_id.replace("-", "_")), where, thing)
        needs["machine"].add(item["handler"])
        if not str(item.get("why", "")).strip():
            raise CodeSpecError(f"{where}: {thing} says why it runs on somebody's machine")
        if item.get("every"):
            try:
                parse_duration(str(item["every"]))
            except ValueError as exc:
                raise CodeSpecError(f"{where}: {thing} every: {exc}") from exc
        needs_table = item.pop("needs", {}) or {}
        if not isinstance(needs_table, dict):
            raise CodeSpecError(f"{where}: {thing} [machine.needs] is a table")
        folders = needs_table.get("folders", [])
        if not isinstance(folders, list) or not all(isinstance(f, dict) for f in folders):
            raise CodeSpecError(f"{where}: {thing} needs.folders is a list of {{ name, access }}")
        names = set()
        for folder_spec in folders:
            name = str(folder_spec.get("name", ""))
            if not FOLDER_RE.match(name) or name in names:
                raise CodeSpecError(f"{where}: {thing} a folder's name is lowercase words with -")
            names.add(name)
            access = folder_spec.setdefault("access", "read")
            if access not in FOLDER_ACCESS:
                raise CodeSpecError(f"{where}: {thing} folder {name} access is read or write")
        run = needs_table.get("run", [])
        if not isinstance(run, list) or not all(isinstance(r, str) and PROGRAM_RE.match(r) for r in run):
            raise CodeSpecError(f"{where}: {thing} needs.run is a list of program names, like [\"lp\"]")
        item["folders"] = folders
        item["run"] = run

    if any(needs.values()) and not code:
        kinds = ", ".join(k for k, v in needs.items() if v)
        raise CodeSpecError(f"{where}: it names {kinds} handlers, so [quill] says where they are: code = \"quill.py\"")

    return CodeSpec(
        code=code,
        sdk=sdk if code else "",
        actions=tuple(actions),
        hooks=tuple(hooks),
        fetch=tuple(fetch),
        secrets=tuple(secrets),
        machine=tuple(machine),
        needs=needs,
    )


# -- the handlers the code has ------------------------------------------------------------
def _decorated(node: ast.AST) -> tuple[str, str] | None:
    """(kind, explicit name or "") for a decorator that registers a handler."""
    target, name = node, ""
    if isinstance(node, ast.Call):
        target = node.func
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            name = node.args[0].value
    kind = target.id if isinstance(target, ast.Name) else target.attr if isinstance(target, ast.Attribute) else ""
    return (kind, name) if kind in HANDLER_KINDS else None


def scan_handlers(folder: Path, code: str) -> dict[str, set[str]]:
    """Every handler the code registers, by kind, read from the source and not run."""
    found: dict[str, set[str]] = {kind: set() for kind in HANDLER_KINDS}
    root = folder / code
    files = sorted(root.rglob("*.py")) if root.is_dir() else [root]
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            raise CodeSpecError(f"{path.relative_to(folder)} does not parse: {exc}") from exc
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for decorator in node.decorator_list:
                hit = _decorated(decorator)
                if hit:
                    found[hit[0]].add(hit[1] or node.name)
    return found


def check_handlers(folder: Path, spec: CodeSpec, where: str) -> dict[str, set[str]]:
    """The code has every handler the manifest names. Returns the ones it has and nobody names."""
    if not spec.code:
        return {}
    have = scan_handlers(folder, spec.code)
    missing = [f"{kind} {name!r}" for kind, names in spec.needs.items() for name in sorted(names - have[kind])]
    if missing:
        raise CodeSpecError(
            f"{where}: the manifest names handlers {spec.code} does not have: {', '.join(missing)}"
        )
    return {kind: names - spec.needs.get(kind, set()) for kind, names in have.items() if names - spec.needs.get(kind, set())}
