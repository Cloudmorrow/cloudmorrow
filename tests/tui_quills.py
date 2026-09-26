"""The Quill half of the fake server the TUI tests drive.

Installed Quills, the catalog, the install sheet, and a record store that
keeps the promises the real one makes (server/records.py): positions inside
`ordered_within` groups, moves that renumber them, stamps, rev checks that
answer 409, cascading deletes, and the per-owner seed that means listing
boards always finds one. A FakeClient mixes this in.

Tasks is the one installed, exactly as `GET /api/quills` sends it; Reading is
a small `list` Quill in the catalog that is not installed yet, so the install
sheet and the list kit have something to show.
"""

from __future__ import annotations

import copy
import datetime as dt
import re

from cloudmorrow.client.api import ApiError

TASK_MODELS = {
    "board": {
        "id": "board",
        "version": 1,
        "label": "Board",
        "description": "A set of tasks, each in one of three lanes.",
        "domain": "tasks",
        "scopes": ["personal"],
        "title": "title",
        "ordered_within": [],
        "source": "foundation",
        "fields": [{"name": "title", "kind": "string", "label": "Title", "required": True}],
    },
    "task": {
        "id": "task",
        "version": 1,
        "label": "Task",
        "description": "One thing to do, on a board, in a lane.",
        "domain": "tasks",
        "scopes": ["personal"],
        "title": "title",
        "ordered_within": ["board", "lane"],
        "source": "foundation",
        "fields": [
            {"name": "board", "kind": "link", "label": "Board", "required": True,
             "indexed": True, "to": "board", "on_delete": "cascade"},
            {"name": "title", "kind": "string", "label": "Title", "required": True},
            {"name": "body", "kind": "markdown", "label": "Body", "default": ""},
            {"name": "lane", "kind": "enum", "label": "Lane", "indexed": True,
             "default": "todo", "values": ["todo", "doing", "done"],
             "labels": ["To Do", "Doing", "Done"]},
            {"name": "due", "kind": "date", "label": "Due", "indexed": True},
            {"name": "done_at", "kind": "datetime", "label": "Done", "indexed": True,
             "stamp": {"field": "lane", "value": "done"}},
        ],
    },
}

TASKS_QUILL = {
    "id": "tasks",
    "name": "Tasks",
    "version": "1.0.0",
    "summary": "Boards with three lanes: To Do, Doing, Done.",
    "category": "personal",
    "icon": "tasks",
    "publisher": "Cloudmorrow",
    "license": "AGPL-3.0-or-later",
    "uses": ["board", "task"],
    "extends": {},
    "introduces": [],
    "grants": [],
    "screens": [
        {"id": "board", "kit": "board", "label": "Tasks", "model": "task", "group": "board",
         "lane": "lane", "title": "title", "body": "body", "done": "done"},
    ],
    "jobs": [
        {"id": "sweep_done", "action": "expire", "model": "task", "field": "done_at",
         "after": "7d", "every": "1h"},
    ],
    "datasets": [{"id": "first_board", "model": "board", "seed": "per-owner", "count": 1}],
    "services": [],
    "webhooks": [],
    "apis": [],
    "data": [
        {"id": "board", "label": "Board", "how": "uses", "foundation": True, "new": False},
        {"id": "task", "label": "Task", "how": "uses", "foundation": True, "new": False},
    ],
    "surfaces": ["phone", "web", "terminal", "command line", "assistant"],
    "installed_version": "1.0.0",
    "runs_code": [],
    "runs_as": "",
    "reach": [],
    "enabled": True,
    "models": TASK_MODELS,
}

READING_QUILL = {
    "id": "reading",
    "name": "Reading",
    "version": "0.2.0",
    "summary": "The books you mean to read, and the ones you have.",
    "category": "home",
    "icon": "book",
    "publisher": "Somebody Else",
    "license": "MIT",
    "uses": [],
    "extends": {},
    "introduces": ["reading.book"],
    "grants": [],
    "screens": [
        {"id": "shelf", "kit": "list", "label": "Reading", "model": "reading.book",
         "title": "title", "subtitle": "author", "tick": "read"},
    ],
    "jobs": [],
    "datasets": [],
    "services": [{"id": "isbn-lookup", "command": ["python", "services/isbn.py"], "always": True}],
    "webhooks": [],
    "apis": [],
    "data": [
        {"id": "reading.book", "label": "Book", "how": "introduces", "foundation": False,
         "new": True},
    ],
    "surfaces": ["phone", "web", "terminal", "command line", "assistant"],
    "installed_version": None,
    "runs_code": ["python services/isbn.py"],
    "runs_as": "",
    "reach": ["reading.book"],
    "enabled": True,
    "models": {
        "reading.book": {
            "id": "reading.book",
            "version": 1,
            "label": "Book",
            "title": "title",
            "ordered_within": [],
            "source": "reading",
            "fields": [
                {"name": "title", "kind": "string", "label": "Title", "required": True},
                {"name": "author", "kind": "string", "label": "Author"},
                {"name": "read", "kind": "bool", "label": "Read", "default": False},
                {"name": "pages", "kind": "int", "label": "Pages"},
            ],
        }
    },
}

SECRET_MODEL = {
    "id": "secret",
    "version": 1,
    "label": "Secret",
    "description": "A key and its value, in a vault and an environment.",
    "domain": "secrets",
    "scopes": ["personal"],
    "title": "key",
    "ordered_within": [],
    "source": "foundation",
    "backend": "vaults",
    "fields": [
        {"name": "vault", "kind": "string", "label": "Vault", "required": True, "indexed": True,
         "default": "default"},
        {"name": "environment", "kind": "string", "label": "Environment", "required": True,
         "indexed": True, "default": "local"},
        {"name": "key", "kind": "string", "label": "Key", "required": True, "indexed": True},
        {"name": "value", "kind": "string", "label": "Value", "secret": True},
        {"name": "length", "kind": "int", "label": "Length", "indexed": True},
    ],
}

SECRETS_QUILL = {
    "id": "secrets",
    "name": "Secrets",
    "version": "1.0.0",
    "summary": "Keys and passwords in vaults and environments, sealed.",
    "category": "developer",
    "icon": "secrets",
    "publisher": "Cloudmorrow",
    "license": "AGPL-3.0-or-later",
    "uses": ["secret"],
    "extends": {},
    "introduces": [],
    "grants": [],
    "screens": [
        {"id": "vaults", "kit": "list", "label": "Secrets", "model": "secret", "title": "key",
         "subtitle": "value", "group": "vault", "subgroup": "environment",
         "fields": ["key", "value", "vault", "environment"]},
    ],
    "jobs": [],
    "datasets": [],
    "services": [],
    "webhooks": [],
    "apis": [],
    "data": [{"id": "secret", "label": "Secret", "how": "uses", "foundation": True, "new": False}],
    "surfaces": ["phone", "web", "terminal", "command line"],
    "installed_version": "1.0.0",
    "runs_code": [],
    "runs_as": "",
    "reach": [],
    "enabled": True,
    "models": {"secret": SECRET_MODEL},
}

# What the server's vaults backend holds; a listing sends every value as null.
SECRET_VALUES = {"s_api": "https://api.example.org", "s_stripe": "sk_live_abc", "s_wifi": "hunter2"}
CALENDAR_MODELS = {
    "calendar": {
        "id": "calendar", "version": 1, "label": "Calendar", "title": "name",
        "scopes": ["personal", "shared", "public"], "ordered_within": [], "source": "foundation",
        "space": True, "in_space": "",
        "fields": [
            {"name": "name", "kind": "string", "label": "Name", "required": True},
            {"name": "colour", "kind": "string", "label": "Colour"},
        ],
    },
    "event": {
        "id": "event", "version": 1, "label": "Event", "title": "title",
        "scopes": ["personal", "shared", "public"], "ordered_within": [], "source": "foundation",
        "space": False, "in_space": "calendar", "authored": "or-manager",
        "fields": [
            {"name": "calendar", "kind": "link", "label": "Calendar", "required": True,
             "indexed": True, "to": "calendar", "on_delete": "cascade"},
            {"name": "title", "kind": "string", "label": "Title", "required": True},
            {"name": "starts_at", "kind": "datetime", "label": "Starts at", "required": True,
             "indexed": True},
            {"name": "ends_at", "kind": "datetime", "label": "Ends at", "indexed": True},
            {"name": "all_day", "kind": "bool", "label": "All day", "default": False,
             "indexed": True},
            {"name": "location", "kind": "string", "label": "Location"},
            {"name": "notes", "kind": "markdown", "label": "Notes"},
        ],
    },
}

CALENDAR_QUILL = {
    **{k: v for k, v in TASKS_QUILL.items() if k not in ("models", "screens", "jobs", "datasets")},
    "id": "calendar",
    "name": "Calendar",
    "summary": "Your own calendar, the ones you share, and one for everybody.",
    "icon": "calendar",
    "uses": ["calendar", "event"],
    "screens": [
        {"id": "month", "kit": "calendar", "label": "Calendar", "model": "event",
         "space": "calendar", "colour": "colour", "title": "title", "subtitle": "location",
         "starts": "starts_at", "ends": "ends_at", "all_day": "all_day"},
    ],
    "jobs": [],
    "datasets": [
        {"id": "yours", "model": "calendar", "seed": "per-owner", "scope": "personal", "count": 1},
        {"id": "everybody", "model": "calendar", "seed": "once", "scope": "public", "count": 1},
    ],
    "models": CALENDAR_MODELS,
}

# Hung on today rather than on a date in the past: the pane opens on the
# month it is, so a fixture from last September would be an empty grid.
TODAY = dt.date.today()
TOMORROW = TODAY + dt.timedelta(days=1)


def space_row(record_id: str, name: str, scope: str, colour: str, *, owner: str = "bram",
              members: list[str] | None = None) -> dict:
    row = record_row("calendar", record_id, 0, name=name, colour=colour)
    row.update(scope=scope, owner=owner, members=list(members or []),
               can_manage=owner == "bram", unread=0)
    return row


def calendar_records() -> dict[str, list[dict]]:
    """bram's own, a shared one guest is in, everybody's; three things on them."""
    def event(record_id, title, calendar, starts, ends, *, all_day=False, owner="bram", **more):
        row = record_row("event", record_id, 0, calendar=calendar, title=title, starts_at=starts,
                         ends_at=ends, all_day=all_day, location=more.get("location", ""), notes="")
        row["owner"] = owner
        return row

    return {
        "calendar": [
            space_row("r_mine", "bram", "personal", "cyan"),
            space_row("r_house", "Household", "shared", "violet", members=["guest"]),
            space_row("r_all", "Everybody", "public", "green", owner="guest"),
        ],
        "event": [
            event("r_dentist", "Dentist", "r_mine", f"{TODAY}T10:00", f"{TODAY}T11:00",
                  location="High Street"),
            event("r_bins", "Bins out", "r_house", str(TODAY), str(TODAY), all_day=True,
                  owner="guest"),
            event("r_boiler", "Boiler service", "r_house", f"{TOMORROW}T09:00",
                  f"{TOMORROW}T10:00"),
        ],
    }


CATALOG = {
    "categories": [
        {"id": "personal", "label": "Personal", "description": "Your own lists and plans."},
        {"id": "home", "label": "Home", "description": "The house and who is in it."},
        {"id": "developer", "label": "Developer", "description": "Machines, secrets, pipelines."},
    ],
    "quills": [
        {"id": "tasks", "name": "Tasks", "summary": TASKS_QUILL["summary"], "repo": "quill-tasks",
         "category": "personal", "publisher": "Cloudmorrow", "foundation": True},
        {"id": "secrets", "name": "Secrets", "summary": SECRETS_QUILL["summary"],
         "repo": "quill-secrets", "category": "developer", "publisher": "Cloudmorrow",
         "foundation": True},
        {"id": "reading", "name": "Reading", "summary": READING_QUILL["summary"],
         "repo": "quill-reading", "category": "home", "publisher": "Somebody Else"},
    ],
}

STAMP = "2026-09-01T09:00:00+00:00"


def record_row(model: str, record_id: str, position: int = 0, **fields) -> dict:
    return {
        "id": record_id,
        "model": model,
        "owner": "bram",
        "scope": "personal",
        "rev": 1,
        "position": position,
        "fields": dict(fields),
        "written_by": "person",
        "created_at": STAMP,
        "updated_at": STAMP,
        "expires_at": None,
    }


def seed_records() -> dict[str, list[dict]]:
    """Two boards, and three tasks on the first — so a test can tell which one it is on."""
    return {
        "board": [
            record_row("board", "r_homelab", 0, title="Home Lab"),
            record_row("board", "r_errands", 1, title="Errands"),
        ],
        "task": [
            record_row("task", "r_task1", 0, board="r_homelab", title="Wire the rack",
                       body="- [ ] label\n- [x] shelf\n", lane="todo", due=None, done_at=None),
            record_row("task", "r_task2", 1, board="r_homelab", title="Repaint", body="",
                       lane="todo", due=None, done_at=None),
            record_row("task", "r_task3", 0, board="r_homelab", title="Swap the switch",
                       body="", lane="doing", due=None, done_at=None),
        ],
        # Two vaults, one with two environments: the shape the Secrets tab always had.
        "secret": [
            record_row("secret", "s_api", 0, vault="verticore", environment="local", key="API_URL",
                       value=SECRET_VALUES["s_api"], length=23),
            record_row("secret", "s_stripe", 0, vault="verticore", environment="production",
                       key="STRIPE_KEY", value=SECRET_VALUES["s_stripe"], length=11),
            record_row("secret", "s_wifi", 0, vault="homelab", environment="local",
                       key="WIFI_PASSWORD", value=SECRET_VALUES["s_wifi"], length=7),
        ],
    }


def _matches(fields: dict, key: str, value: object) -> bool:
    """A filter as the server reads it: `name` is equal, `name__gte` a range."""
    name, _, op = key.rpartition("__")
    if op in ("lt", "lte", "gt", "gte"):
        have = fields.get(name)
        if have is None:
            return False
        return {"lt": have < value, "lte": have <= value, "gt": have > value,
                "gte": have >= value}[op]
    return fields.get(key) == value


def _after(value: str) -> dt.timedelta:
    match = re.fullmatch(r"(\d+)([mhdw])", value)
    count, unit = int(match.group(1)), match.group(2)
    return dt.timedelta(**{{"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}[unit]: count})


class FakeQuills:
    """Installed Quills, the catalog, and the record store — mixed into FakeClient."""

    def setup_quills(self) -> None:
        self.quill_list: list[dict] = [copy.deepcopy(TASKS_QUILL)]
        self.catalog: dict = copy.deepcopy(CATALOG)
        self.record_store: dict[str, list[dict]] = seed_records()
        # What was asked of the store, for tests to read back.
        self.record_calls: list[tuple[str, dict]] = []
        self.moves: list[tuple[str, dict, int | None]] = []
        self.quill_calls: list[tuple[str, str]] = []
        # Every record read on its own, so a test can see a value was asked for.
        self.record_reads: list[tuple[str, str]] = []
        self._next_id = 100

    # -- the Quills ------------------------------------------------------------
    async def quills(self) -> list[dict]:
        return copy.deepcopy(self.quill_list)

    async def quill_catalog(self) -> dict:
        installed = {q["id"]: q["version"] for q in self.quill_list}
        return {
            "categories": list(self.catalog["categories"]),
            "quills": [
                {**entry, "installed_version": installed.get(entry["id"])}
                for entry in self.catalog["quills"]
            ],
        }

    def _published(self, quill_id: str) -> dict:
        for quill in (TASKS_QUILL, READING_QUILL, SECRETS_QUILL):
            if quill["id"] == quill_id:
                return copy.deepcopy(quill)
        raise ApiError(f"{quill_id} is not in the catalog", status_code=400)

    async def plan_quill(self, *, id: str = "", source: str = "", ref: str = "") -> dict:
        self.quill_calls.append(("plan", id))
        plan = self._published(id)
        plan.pop("models", None)
        plan.pop("enabled", None)
        installed = next((q for q in self.quill_list if q["id"] == id), None)
        plan["installed_version"] = installed["version"] if installed else None
        return plan

    async def install_quill(self, *, id: str = "", source: str = "", ref: str = "") -> dict:
        self.quill_calls.append(("install", id))
        quill = self._published(id)
        quill["installed_version"] = quill["version"]
        self.quill_list = [q for q in self.quill_list if q["id"] != id] + [quill]
        # Installed Quills are features like the built-in ones.
        if not any(row["key"] == id for row in self.feature_list):
            from tests.tui_harness import feature_row

            self.feature_list.append(feature_row(id, quill["name"]))
        return await self.plan_quill(id=id)

    # -- a Quill's running code: set `running` to what the server would say --
    running: list[dict] = []

    async def quill_services(self) -> list[dict]:
        return copy.deepcopy(self.running)

    async def restart_quill(self, quill_id: str) -> dict:
        self.quill_calls.append(("restart", quill_id))
        return {"restarted": quill_id}

    async def rotate_quill_token(self, quill_id: str) -> dict:
        self.quill_calls.append(("token", quill_id))
        return {"token": {"issued_at": "now"}}

    async def rotate_webhook_secret(self, quill_id: str, hook_id: str) -> dict:
        self.quill_calls.append(("secret", quill_id, hook_id))
        return {"id": hook_id, "secret": "new"}

    async def uninstall_quill(self, quill_id: str) -> None:
        self.quill_calls.append(("uninstall", quill_id))
        self.quill_list = [q for q in self.quill_list if q["id"] != quill_id]
        self.feature_list = [row for row in self.feature_list if row["key"] != quill_id]

    # -- the datamodels ---------------------------------------------------------
    def _models(self) -> dict[str, dict]:
        models: dict[str, dict] = {}
        for quill in self.quill_list:
            models.update(quill.get("models") or {})
        return models

    def _model(self, model_id: str) -> dict:
        model = self._models().get(model_id)
        if model is None:
            raise ApiError(f"no datamodel {model_id}", status_code=404)
        return model

    async def datamodels(self) -> list[dict]:
        return list(self._models().values())

    # -- records -----------------------------------------------------------------
    def _rows(self, model_id: str) -> list[dict]:
        return self.record_store.setdefault(model_id, [])

    def _find(self, model_id: str, record_id: str) -> dict:
        for row in self._rows(model_id):
            if row["id"] == record_id:
                return row
        raise ApiError(f"no {model_id} {record_id}", status_code=404)

    def _group(self, model: dict, row: dict) -> tuple:
        return tuple(row["fields"].get(name) for name in model.get("ordered_within") or [])

    def _renumber(self, model: dict, group: tuple) -> None:
        same = sorted(
            (r for r in self._rows(model["id"]) if self._group(model, r) == group),
            key=lambda r: r["position"],
        )
        for index, row in enumerate(same):
            row["position"] = index

    def _stamp(self, model: dict, row: dict) -> None:
        """Stamped fields follow the field they watch; expire jobs set the clock."""
        for f in model["fields"]:
            stamp = f.get("stamp")
            if not stamp:
                continue
            if row["fields"].get(stamp["field"]) == stamp["value"]:
                if not row["fields"].get(f["name"]):
                    row["fields"][f["name"]] = dt.datetime.now(tz=dt.UTC).isoformat(
                        timespec="seconds"
                    )
            else:
                row["fields"][f["name"]] = None
        row["expires_at"] = None
        for quill in self.quill_list:
            for job in quill.get("jobs") or []:
                if job.get("action") != "expire" or job.get("model") != model["id"]:
                    continue
                moment = row["fields"].get(job["field"])
                if moment:
                    row["expires_at"] = (
                        dt.datetime.fromisoformat(moment) + _after(job["after"])
                    ).isoformat(timespec="seconds")

    def _seed(self, model_id: str) -> None:
        """A per-owner dataset: the first board, made the first time boards are listed."""
        if self._rows(model_id):
            return
        for quill in self.quill_list:
            for dataset in quill.get("datasets") or []:
                if dataset.get("model") == model_id and dataset.get("seed") == "per-owner":
                    self._rows(model_id).append(
                        record_row(model_id, self._fresh_id(), 0, title="bram's tasks")
                    )
                    return

    def _fresh_id(self) -> str:
        self._next_id += 1
        return f"r_new{self._next_id}"

    async def records(self, model: str, **where: object) -> list[dict]:
        self.record_calls.append((model, dict(where)))
        definition = self._model(model)
        self._seed(model)
        rows = [row for row in self._rows(model) if all(
            _matches(row["fields"], key, value) for key, value in where.items())]
        order = definition.get("ordered_within") or []
        rows.sort(key=lambda r: (tuple(str(r["fields"].get(n)) for n in order), r["position"]))
        rows = copy.deepcopy(rows)
        # A secret field is never in a listing, as the server promises.
        for f in definition["fields"]:
            if f.get("secret"):
                for row in rows:
                    row["fields"][f["name"]] = None
        return rows

    async def record(self, model: str, record_id: str) -> dict:
        self.record_reads.append((model, record_id))
        return copy.deepcopy(self._find(model, record_id))

    async def create_record(
        self, model: str, fields: dict, *, index: int | None = None, scope: str | None = None
    ) -> dict:
        self.record_calls.append((f"create:{model}", dict(fields, _scope=scope)))
        definition = self._model(model)
        values: dict = {}
        for f in definition["fields"]:
            if f["name"] in fields:
                values[f["name"]] = fields[f["name"]]
            else:
                values[f["name"]] = f.get("default")
            if f.get("required") and values[f["name"]] in (None, ""):
                raise ApiError(f"{model}.{f['name']} is required", status_code=400)
        row = record_row(model, self._fresh_id(), 0, **values)
        if definition.get("space"):
            row.update(scope=scope or "shared", members=[], can_manage=True, unread=0)
        group = self._group(definition, row)
        same = [r for r in self._rows(model) if self._group(definition, r) == group]
        row["position"] = len(same) if index is None else index - 0.5
        self._stamp(definition, row)
        self._rows(model).append(row)
        self._renumber(definition, group)
        return copy.deepcopy(row)

    async def update_record(
        self, model: str, record_id: str, fields: dict, *, rev: int | None = None
    ) -> dict:
        definition = self._model(model)
        row = self._find(model, record_id)
        if rev is not None and rev != row["rev"]:
            raise ApiError("the record changed since you read it", status_code=409)
        before = self._group(definition, row)
        row["fields"].update(fields)
        row["rev"] += 1
        self._stamp(definition, row)
        after = self._group(definition, row)
        if after != before:
            row["position"] = 10_000
            self._renumber(definition, before)
            self._renumber(definition, after)
        return copy.deepcopy(row)

    async def move_record(
        self, model: str, record_id: str, fields: dict, index: int | None = None
    ) -> dict:
        self.moves.append((record_id, dict(fields), index))
        definition = self._model(model)
        row = self._find(model, record_id)
        before = self._group(definition, row)
        row["fields"].update(fields)
        row["rev"] += 1
        self._stamp(definition, row)
        after = self._group(definition, row)
        # Out of the old place, into the new one: half a step before the card
        # it lands in front of, and the renumbering tidies it.
        row["position"] = 10_000 if index is None else index - 0.5
        if after == before and index is not None:
            others = sorted(
                (r for r in self._rows(model)
                 if self._group(definition, r) == after and r is not row),
                key=lambda r: r["position"],
            )
            for number, other in enumerate(others):
                other["position"] = number
        self._renumber(definition, before)
        self._renumber(definition, after)
        return copy.deepcopy(row)

    async def delete_record(self, model: str, record_id: str) -> None:
        definition = self._model(model)
        row = self._find(model, record_id)
        self.record_store[model] = [r for r in self._rows(model) if r["id"] != record_id]
        self._renumber(definition, self._group(definition, row))
        # Cascade: whatever links here with on_delete = "cascade" goes too.
        for other in self._models().values():
            for f in other["fields"]:
                if f.get("kind") != "link" or f.get("to") != model:
                    continue
                if f.get("on_delete") != "cascade":
                    continue
                rows = self._rows(other["id"])
                for linked in [r for r in rows if r["fields"].get(f["name"]) == record_id]:
                    await self.delete_record(other["id"], linked["id"])

    # -- the people in a space ----------------------------------------------------
    async def people(self) -> list[dict]:
        return [{"username": "guest", "display_name": "Guest"},
                {"username": "ada", "display_name": ""}]

    async def add_member(self, model: str, space_id: str, username: str) -> dict:
        self.record_calls.append((f"add:{space_id}", {"username": username}))
        row = self._find(model, space_id)
        if row.get("scope") != "shared":
            raise ApiError("only a shared one has members", status_code=400)
        if username not in row["members"]:
            row["members"].append(username)
        return copy.deepcopy(row)

    async def remove_member(self, model: str, space_id: str, username: str) -> None:
        self.record_calls.append((f"remove:{space_id}", {"username": username}))
        row = self._find(model, space_id)
        row["members"] = [m for m in row.get("members") or [] if m != username]
        if username == "bram":
            self.record_store[model] = [r for r in self._rows(model) if r["id"] != space_id]
