"""Datamodels: the kinds of data a Quill may use, and what a record of each holds.

A datamodel is a TOML file. The foundational ones come from the
`Cloudmorrow/datamodels` repository and are kept, once installed, in
`<data_dir>/datamodels/`; the ones a Quill introduces live in that Quill's
own `datamodels/` folder, under an id that starts with the Quill's. Either
way this module reads the file into a `Datamodel` and checks it, and the
record store trusts nothing it has not checked.

Extension fields — a Quill's own fields on somebody else's datamodel — are
merged in here too, under `<quill>.<field>`, so everything downstream sees
one list of fields per datamodel and never has to ask where one came from.

See docs/QUILLS.md for the format.
"""

from __future__ import annotations

import datetime as dt
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "Datamodel",
    "DatamodelError",
    "Field",
    "FIELD_KINDS",
    "SCOPES",
    "load_datamodel",
    "parse_datamodel",
    "parse_duration",
]

# Every kind has a widget on every surface, so the list is short on purpose.
FIELD_KINDS = frozenset(
    {
        "string",
        "text",
        "markdown",
        "bool",
        "int",
        "decimal",
        "date",
        "datetime",
        "enum",
        "email",
        "phone",
        "url",
        "link",
        "json",
    }
)

SCOPES = frozenset({"personal", "shared", "public"})
# What the record store does today. A datamodel asking for more is refused
# at install, with that said, rather than quietly stored as personal.
SUPPORTED_SCOPES = frozenset({"personal", "shared", "public"})

# Where a datamodel's records live, when not in the record store. Each is a
# store the core has always had and other things reach directly; see
# `server/backends.py`.
BACKENDS = frozenset({"notes", "shares", "vaults"})

NOTIFY_WHEN = frozenset({"created"})

# `task`, `board`, `fleet.service_visit`, and an extension's `fleet.odometer`.
ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}(\.[a-z][a-z0-9_]{0,39})?$")
FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


class DatamodelError(ValueError):
    """A datamodel file that does not say something the core can use."""


@dataclass(frozen=True, slots=True)
class Field:
    name: str
    kind: str
    label: str = ""
    required: bool = False
    indexed: bool = False
    default: object = None
    # enum
    values: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()
    # link
    to: str = ""
    on_delete: str = ""
    # datetime: set when `stamp_field` takes `stamp_value`, cleared when it leaves
    stamp_field: str = ""
    stamp_value: str = ""
    # Which Quill added it, for an extension field; empty for a standard one.
    added_by: str = ""
    # Hidden until asked for: never in a listing, drawn masked with a way to
    # reveal it on every surface. A string or text field.
    secret: bool = False

    def label_for(self, value: str) -> str:
        """An enum value as a person reads it."""
        if value in self.values and self.labels:
            return self.labels[self.values.index(value)]
        return value

    def to_dict(self) -> dict:
        row: dict = {"name": self.name, "kind": self.kind, "label": self.label or _label(self.name)}
        if self.required:
            row["required"] = True
        if self.indexed:
            row["indexed"] = True
        if self.default is not None:
            row["default"] = self.default
        if self.values:
            row["values"] = list(self.values)
            row["labels"] = list(self.labels or self.values)
        if self.to:
            row["to"] = self.to
            if self.on_delete:
                row["on_delete"] = self.on_delete
        if self.stamp_field:
            row["stamp"] = {"field": self.stamp_field, "value": self.stamp_value}
        if self.added_by:
            row["added_by"] = self.added_by
        if self.secret:
            row["secret"] = True
        return row


@dataclass(frozen=True, slots=True)
class Datamodel:
    id: str
    version: int
    label: str
    description: str
    domain: str
    scopes: tuple[str, ...]
    fields: tuple[Field, ...]
    title: str
    ordered_within: tuple[str, ...] = ()
    # Where it came from: "foundation", or the id of the Quill that introduced it.
    source: str = "foundation"
    extras: dict = field(default_factory=dict)
    # A record of it is a space: personal, shared with members, or public.
    space: bool = False
    # The link field naming the space a record of it is in, if it lives in one.
    in_space: str = ""
    # Only the one who wrote a record may change or delete it: a message.
    authored: bool = False
    # What happens when a record of it is written in a space.
    notify: tuple[dict, ...] = ()
    # Not in the record store: served by this backend instead.
    backend: str = ""

    @property
    def by_name(self) -> dict[str, Field]:
        return {f.name: f for f in self.fields}

    @property
    def ordered(self) -> bool:
        return bool(self.ordered_within)

    def get_field(self, name: str) -> Field:
        try:
            return self.by_name[name]
        except KeyError:
            raise DatamodelError(f"{self.id} has no field {name!r}") from None

    def indexed(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields if f.indexed)

    def with_extension(self, quill: str, fields: dict[str, dict]) -> Datamodel:
        """This datamodel with *quill*'s own fields added, as `<quill>.<name>`."""
        added = []
        for name, spec in fields.items():
            if not FIELD_RE.match(name):
                raise DatamodelError(f"{quill} extends {self.id} with a bad field name {name!r}")
            parsed = _field(f"{self.id} (extended by {quill})", name, spec)
            if parsed.required:
                raise DatamodelError(f"{quill}.{name}: an extension field cannot be required")
            added.append(_replace(parsed, name=f"{quill}.{name}", added_by=quill))
        taken = {f.name for f in self.fields}
        for f in added:
            if f.name in taken:
                raise DatamodelError(f"{self.id} already has a field {f.name!r}")
        return Datamodel(
            id=self.id,
            version=self.version,
            label=self.label,
            description=self.description,
            domain=self.domain,
            scopes=self.scopes,
            fields=self.fields + tuple(added),
            title=self.title,
            ordered_within=self.ordered_within,
            source=self.source,
            extras=self.extras,
            space=self.space,
            in_space=self.in_space,
            authored=self.authored,
            notify=self.notify,
            backend=self.backend,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "version": self.version,
            "label": self.label,
            "description": self.description,
            "domain": self.domain,
            "scopes": list(self.scopes),
            "title": self.title,
            "ordered_within": list(self.ordered_within),
            "source": self.source,
            "space": self.space,
            "in_space": self.in_space,
            "authored": self.authored,
            "notify": list(self.notify),
            "backend": self.backend,
            "fields": [f.to_dict() for f in self.fields],
        }


def _label(name: str) -> str:
    return name.rsplit(".", 1)[-1].replace("_", " ").capitalize()


def _replace(f: Field, **changes) -> Field:
    values = {name: getattr(f, name) for name in Field.__slots__}
    values.update(changes)
    return Field(**values)


def _field(where: str, name: str, spec: object) -> Field:
    if not isinstance(spec, dict):
        raise DatamodelError(f"{where}: field {name!r} must be a table")
    kind = spec.get("kind")
    if kind not in FIELD_KINDS:
        raise DatamodelError(
            f"{where}: field {name!r} has kind {kind!r}; one of {', '.join(sorted(FIELD_KINDS))}"
        )
    known = {
        "kind",
        "label",
        "required",
        "indexed",
        "default",
        "values",
        "labels",
        "to",
        "on_delete",
        "stamp",
        "description",
        "secret",
    }
    unknown = set(spec) - known
    if unknown:
        raise DatamodelError(f"{where}: field {name!r} has unknown keys {sorted(unknown)}")
    values = tuple(str(v) for v in spec.get("values", ()))
    labels = tuple(str(v) for v in spec.get("labels", ()))
    if kind == "enum":
        if not values:
            raise DatamodelError(f"{where}: enum field {name!r} needs values")
        if labels and len(labels) != len(values):
            raise DatamodelError(
                f"{where}: {name!r} has {len(labels)} labels for {len(values)} values"
            )
    elif values or labels:
        raise DatamodelError(f"{where}: only an enum field has values")
    to = str(spec.get("to", ""))
    on_delete = str(spec.get("on_delete", ""))
    if kind == "link":
        if not to:
            raise DatamodelError(f"{where}: link field {name!r} needs `to`")
        if on_delete not in ("", "cascade", "clear"):
            raise DatamodelError(f"{where}: {name!r} on_delete is cascade or clear")
    elif to or on_delete:
        raise DatamodelError(f"{where}: only a link field has `to` and `on_delete`")
    stamp = spec.get("stamp") or {}
    if stamp and (kind != "datetime" or set(stamp) != {"field", "value"}):
        raise DatamodelError(f"{where}: {name!r} stamp is {{ field, value }} on a datetime")
    secret = spec.get("secret", False)
    if not isinstance(secret, bool):
        raise DatamodelError(f"{where}: {name!r} secret is true or false")
    if secret and (kind not in ("string", "text") or spec.get("indexed")):
        raise DatamodelError(f"{where}: {name!r} is secret, so it is a string or text, never indexed")
    default = spec.get("default")
    if kind == "enum" and default is not None and str(default) not in values:
        raise DatamodelError(f"{where}: {name!r} default {default!r} is not one of its values")
    return Field(
        name=name,
        kind=kind,
        label=str(spec.get("label", "")),
        required=bool(spec.get("required", False)),
        indexed=bool(spec.get("indexed", False)),
        default=default,
        values=values,
        labels=labels,
        to=to,
        on_delete=on_delete,
        stamp_field=str(stamp.get("field", "")),
        stamp_value=str(stamp.get("value", "")),
        secret=secret,
    )


def parse_datamodel(data: dict, *, source: str = "foundation", where: str = "") -> Datamodel:
    """A datamodel from the parsed TOML, checked on its own.

    Links to other datamodels are checked by the registry, which knows what
    else is installed; everything that can be checked alone is checked here.
    """
    head = data.get("datamodel")
    if not isinstance(head, dict):
        raise DatamodelError(f"{where or 'datamodel'}: no [datamodel] table")
    model_id = str(head.get("id", ""))
    where = where or model_id or "datamodel"
    if not ID_RE.match(model_id):
        raise DatamodelError(
            f"{where}: id {model_id!r} is lowercase words, optionally `quill.name`"
        )
    if source != "foundation" and not model_id.startswith(source + "."):
        raise DatamodelError(f"{where}: a datamodel {source} introduces is named {source}.<name>")
    if source == "foundation" and "." in model_id:
        raise DatamodelError(f"{where}: a foundational datamodel has a plain id")
    raw_fields = data.get("fields")
    if not isinstance(raw_fields, dict) or not raw_fields:
        raise DatamodelError(f"{where}: no [fields]")
    fields = []
    for name, spec in raw_fields.items():
        if not FIELD_RE.match(name):
            raise DatamodelError(f"{where}: bad field name {name!r}")
        fields.append(_field(where, name, spec))
    by_name = {f.name: f for f in fields}
    for f in fields:
        if f.stamp_field:
            watched = by_name.get(f.stamp_field)
            if watched is None:
                raise DatamodelError(f"{where}: {f.name!r} stamps on a field that is not there")
            if watched.kind == "enum" and f.stamp_value not in watched.values:
                raise DatamodelError(
                    f"{where}: {f.name!r} stamps on a value {watched.name} never has"
                )
    scopes = tuple(str(s) for s in head.get("scopes", ["personal"]))
    if not scopes or not set(scopes) <= SCOPES:
        raise DatamodelError(f"{where}: scopes are some of {', '.join(sorted(SCOPES))}")
    title = str(head.get("title", ""))
    if not title:
        title = next((f.name for f in fields if f.kind in ("string", "text")), "")
    if title not in by_name:
        raise DatamodelError(f"{where}: title {title!r} is not one of its fields")
    ordered_within = tuple(str(n) for n in head.get("ordered_within", ()))
    for name in ordered_within:
        if name not in by_name or not by_name[name].indexed:
            raise DatamodelError(
                f"{where}: ordered_within names {name!r}, which must be an indexed field"
            )
    version = head.get("version", 1)
    if not isinstance(version, int) or version < 1:
        raise DatamodelError(f"{where}: version is a whole number from 1")
    space = bool(head.get("space", False))
    in_space = str(head.get("in_space", ""))
    if space and in_space:
        raise DatamodelError(f"{where}: a space is not in another space")
    if space and not set(scopes) - {"personal"}:
        raise DatamodelError(f"{where}: a space is shared or public in at least one of its scopes")
    if in_space:
        link = by_name.get(in_space)
        if link is None or link.kind != "link":
            raise DatamodelError(f"{where}: in_space names {in_space!r}, which must be a link field")
    notify = []
    for rule in data.get("notify", []):
        if not isinstance(rule, dict) or rule.get("when") not in NOTIFY_WHEN or rule.get("to") != "members":
            raise DatamodelError(f"{where}: a notify rule is when = \"created\", to = \"members\"")
        if not in_space:
            raise DatamodelError(f"{where}: only a datamodel in a space notifies its members")
        notify.append({"when": "created", "to": "members", "push": bool(rule.get("push", False)),
                       "unread": bool(rule.get("unread", False))})
    backend = str(head.get("backend", ""))
    if backend and backend not in BACKENDS:
        raise DatamodelError(f"{where}: backend is one of {', '.join(sorted(BACKENDS))}")
    if backend and source != "foundation":
        raise DatamodelError(f"{where}: only a foundational datamodel has a backend")
    return Datamodel(
        id=model_id,
        version=version,
        label=str(head.get("label", "")) or _label(model_id),
        description=str(head.get("description", "")),
        domain=str(head.get("domain", "")),
        scopes=scopes,
        fields=tuple(fields),
        title=title,
        ordered_within=ordered_within,
        source=source,
        space=space,
        in_space=in_space,
        authored=bool(head.get("authored", False)),
        notify=tuple(notify),
        backend=backend,
    )


def load_datamodel(path: Path, *, source: str = "foundation") -> Datamodel:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise DatamodelError(f"{path.name}: {exc}") from exc
    return parse_datamodel(data, source=source, where=path.name)


_DURATION_RE = re.compile(r"^(\d+)\s*([smhdw])$")
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 7 * 86400}


def parse_duration(text: str) -> dt.timedelta:
    """`15m`, `1h`, `7d`, `2w`."""
    match = _DURATION_RE.match((text or "").strip().lower())
    if not match:
        raise ValueError(f"{text!r} is not a duration like 15m, 1h, 7d")
    return dt.timedelta(seconds=int(match.group(1)) * _UNITS[match.group(2)])
