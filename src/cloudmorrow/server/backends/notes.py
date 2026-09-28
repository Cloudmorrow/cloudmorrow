"""Notes as records: a note's id is its path, and its folders and pictures come with it."""

from __future__ import annotations

from collections.abc import Callable

from cloudmorrow.paths import UnsafePathError, normalise_rel_path
from cloudmorrow.server.backends.base import AttachmentTooBig, decode_id, encode_id, iso_stamp
from cloudmorrow.server.datamodels import Datamodel
from cloudmorrow.server.notes import (
    IMAGE_DIR,
    NOTE_SUFFIX,
    InvalidImageError,
    NoteConflictError,
    NoteExistsError,
    NoteNode,
    NoteNotFoundError,
    NoteStore,
)
from cloudmorrow.server.records import (
    Principal,
    Record,
    RecordConflictError,
    RecordError,
    UnknownRecordError,
)


class NotesBackend:
    """Notes as records: each Markdown file in a person's notes folder is one.

    Fields: `path` (the note's title as a path, folders and all, without
    `.md`), `folder` and `title` (the two halves of it, for grouping and
    lists), `body` (the Markdown), and `modified`. A listing leaves `body`
    out — a folder of long notes is a lot to send for a list of titles — and
    reading one note puts it in. Moving a note is changing its `path`, or
    its `folder` or `title`, which is the same thing said in halves.

    Folders are the folders on disk; attachments are the pictures in
    `img/`, which a note points at as `![alt](img/<name>)`.
    """

    PREFIX = "n_"

    def __init__(self, store_for: Callable[[str], NoteStore]) -> None:
        self._store_for = store_for

    def _record(self, model: Datamodel, owner: str, path: str, *, body: str | None,
                rev: str, modified: float, preview: str | None = None) -> Record:
        title_path = path[: -len(NOTE_SUFFIX)] if path.endswith(NOTE_SUFFIX) else path
        folder, _, title = title_path.rpartition("/")
        return Record(
            id=encode_id(self.PREFIX, title_path),
            model=model.id,
            owner=owner,
            scope="personal",
            rev=rev,
            position=0,
            fields={"path": title_path, "folder": folder, "title": title, "body": body,
                    "modified": iso_stamp(modified)},
            written_by="notes",
            created_at=iso_stamp(modified),
            updated_at=iso_stamp(modified),
            preview=preview,
        )

    def _walk(self, node: NoteNode, into: list[NoteNode]) -> None:
        for child in node.children:
            if child.is_dir:
                self._walk(child, into)
            else:
                into.append(child)

    def list(self, principal: Principal, model: Datamodel, where: dict, *, q: str = "",
             previews: bool = False) -> list[Record]:
        unknown = set(where) - {"folder"}
        if unknown:
            raise RecordError(f"notes are filtered by folder only, not {', '.join(sorted(unknown))}")
        store = self._store_for(principal.username)
        found: list[NoteNode] = []
        self._walk(store.tree(previews=previews and not q), found)
        # A search is the notes' own: names and every line, the files read
        # one by one. Its first line that matched is the preview.
        hits: dict[str, str] | None = None
        if q:
            hits = {}
            for result in store.search(q):
                lines = [m["text"] for m in result["matches"] if m["line"] > 0]
                hits[result["path"]] = lines[0].strip() if lines else ""
        folder = where.get("folder")
        records = []
        for node in sorted(found, key=lambda n: n.path.casefold()):
            if hits is not None and node.path not in hits:
                continue
            preview = hits[node.path] if hits is not None else node.preview
            record = self._record(model, principal.username, node.path, body=None,
                                  rev="", modified=node.modified or 0, preview=preview)
            if folder is not None and record.fields["folder"] != folder:
                continue
            records.append(record)
        return records

    def get(self, principal: Principal, model: Datamodel, record_id: str) -> Record:
        path = decode_id(self.PREFIX, record_id)
        store = self._store_for(principal.username)
        try:
            note = store.read(store.with_suffix(path))
        except (NoteNotFoundError, UnsafePathError, IsADirectoryError):
            raise UnknownRecordError(record_id) from None
        return self._record(model, principal.username, note.path, body=note.content,
                            rev=note.rev, modified=note.modified)

    @staticmethod
    def _path_from(fields: dict, *, folder: str = "", title: str = "") -> str:
        """A note's path from what was sent: `path`, or `folder` and `title`."""
        if fields.get("path"):
            return str(fields["path"]).strip().strip("/")
        folder = str(fields.get("folder", folder) or "").strip().strip("/")
        title = str(fields.get("title", title) or "").strip().replace("/", "-")
        return f"{folder}/{title}" if folder and title else title

    def create(self, principal: Principal, model: Datamodel, fields: dict) -> Record:
        path = self._path_from(fields)
        if not path:
            raise RecordError("a note needs a path: its title, with folders if you like")
        store = self._store_for(principal.username)
        try:
            note = store.create_note(store.with_suffix(path), str(fields.get("body") or ""))
        except NoteExistsError:
            raise RecordError(f"there is already a note called {path}") from None
        except UnsafePathError as exc:
            raise RecordError(str(exc)) from None
        return self.get(principal, model, encode_id(self.PREFIX, note.path.removesuffix(NOTE_SUFFIX)))

    def update(self, principal: Principal, model: Datamodel, record_id: str, fields: dict,
               rev: object) -> Record:
        unknown = set(fields) - {"path", "folder", "title", "body"}
        if unknown:
            raise RecordError(f"a note's {', '.join(sorted(unknown))} is not written directly")
        current = self.get(principal, model, record_id)
        store = self._store_for(principal.username)
        path = current.fields["path"]
        if "body" in fields:
            try:
                store.write(store.with_suffix(path), str(fields["body"] or ""),
                            rev=str(rev) if rev else None)
            except NoteConflictError:
                raise RecordConflictError(self.get(principal, model, record_id)) from None
        new_path = self._path_from(
            fields, folder=current.fields["folder"], title=current.fields["title"]
        ) or path
        if new_path != path:
            try:
                moved = store.move(store.with_suffix(path), store.with_suffix(new_path))
            except (NoteExistsError, FileExistsError):
                raise RecordError(f"there is already a note called {new_path}") from None
            except UnsafePathError as exc:
                raise RecordError(str(exc)) from None
            path = moved.removesuffix(NOTE_SUFFIX)
        return self.get(principal, model, encode_id(self.PREFIX, path))

    def delete(self, principal: Principal, model: Datamodel, record_id: str) -> int:
        current = self.get(principal, model, record_id)
        store = self._store_for(principal.username)
        store.delete(store.with_suffix(current.fields["path"]))
        return 1

    # -- folders ---------------------------------------------------------------------
    @staticmethod
    def _folder_path(path: str) -> str:
        try:
            rel = normalise_rel_path(str(path or "")).as_posix()
        except UnsafePathError as exc:
            raise RecordError(str(exc)) from None
        if rel.split("/", 1)[0] == IMAGE_DIR:
            raise RecordError(f"{IMAGE_DIR} is where the pictures are kept; call the folder something else")
        return rel

    def folders(self, principal: Principal, model: Datamodel) -> list[dict]:
        store = self._store_for(principal.username)
        found: list[dict] = []

        def walk(node: NoteNode) -> None:
            for child in node.children:
                if child.is_dir:
                    notes = sum(1 for c in child.children if not c.is_dir)
                    found.append({"path": child.path, "name": child.name, "count": notes})
                    walk(child)

        walk(store.tree())
        return found

    def make_folder(self, principal: Principal, model: Datamodel, path: str) -> dict:
        store = self._store_for(principal.username)
        rel = self._folder_path(path)
        try:
            made = store.create_dir(rel)
        except NoteExistsError:
            raise RecordError(f"there is already a folder called {rel}") from None
        except UnsafePathError as exc:
            raise RecordError(str(exc)) from None
        return {"path": made, "name": made.rsplit("/", 1)[-1]}

    def move_folder(self, principal: Principal, model: Datamodel, path: str, to: str) -> dict:
        store = self._store_for(principal.username)
        source, target = self._folder_path(path), self._folder_path(to)
        if not (store.root / source).is_dir():
            raise RecordError(f"there is no folder called {source}")
        try:
            moved = store.move(source, target)
        except (NoteExistsError, FileExistsError):
            raise RecordError(f"there is already something called {target}") from None
        except (NoteNotFoundError, UnsafePathError) as exc:
            raise RecordError(str(exc)) from None
        return {"path": moved, "name": moved.rsplit("/", 1)[-1]}

    def delete_folder(self, principal: Principal, model: Datamodel, path: str) -> None:
        store = self._store_for(principal.username)
        rel = self._folder_path(path)
        if not (store.root / rel).is_dir():
            raise RecordError(f"there is no folder called {rel}")
        try:
            store.delete(rel, recursive=True)
        except (NoteNotFoundError, UnsafePathError) as exc:
            raise RecordError(str(exc)) from None

    # -- attachments: the pictures -------------------------------------------------------
    def attach(self, principal: Principal, model: Datamodel, data: bytes, filename: str) -> dict:
        store = self._store_for(principal.username)
        try:
            info = store.save_image(data, filename=filename)
        except InvalidImageError as exc:
            if "too big" in str(exc):
                raise AttachmentTooBig(str(exc)) from None
            raise RecordError(str(exc)) from None
        return info.to_dict()

    def attachment(self, principal: Principal, model: Datamodel, name: str) -> tuple[bytes, str]:
        store = self._store_for(principal.username)
        try:
            return store.image(name)
        except (NoteNotFoundError, UnsafePathError):
            raise UnknownRecordError(name) from None
