"""The nested tree of folders and pages: the kit editor's left-hand side."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.message import Message
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

NOTE_ICON = "· "


def _label(node: dict[str, Any], expanded: bool = False) -> Text:
    """Folders get Textual's own expand arrow, so only leaves carry an icon."""
    name = node["name"]
    if node["is_dir"]:
        return Text(name, style="bold #7dd3fc")
    text = Text(NOTE_ICON, style="dim")
    text.append(name.removesuffix(".md"), style="#d7dbe4")
    return text


class NoteTree(Tree[dict]):
    """A Tree of folders and notes, with keys for the usual file operations."""

    BINDINGS = [
        ("n", "new_note", "New note"),
        ("N", "new_folder", "New folder"),
        ("r", "rename", "Rename"),
        ("d", "delete", "Delete"),
        ("slash", "search", "Search"),
    ]

    class NoteSelected(Message):
        def __init__(self, path: str) -> None:
            self.path = path
            super().__init__()

    class NewNoteRequested(Message):
        def __init__(self, parent: str) -> None:
            self.parent = parent
            super().__init__()

    class NewFolderRequested(Message):
        def __init__(self, parent: str) -> None:
            self.parent = parent
            super().__init__()

    class RenameRequested(Message):
        def __init__(self, path: str, is_dir: bool) -> None:
            self.path = path
            self.is_dir = is_dir
            super().__init__()

    class DeleteRequested(Message):
        def __init__(self, path: str, is_dir: bool) -> None:
            self.path = path
            self.is_dir = is_dir
            super().__init__()

    class SearchRequested(Message):
        pass

    class ReloadRequested(Message):
        pass

    def __init__(self, *, label: str = "notes", **kwargs: Any) -> None:
        # What the top of the tree is called: the screen's own name.
        self.root_label = label
        super().__init__(label, data={"name": label, "path": "", "is_dir": True}, **kwargs)
        self.show_root = True
        self.guide_depth = 2
        self._expanded: set[str] = {""}

    # -- building ----------------------------------------------------------
    def load_tree(self, payload: dict[str, Any], *, select: str | None = None) -> None:
        """Rebuild from a tree of `{name, path, is_dir, children}`, keeping what was open."""
        self.clear()
        self.root.data = {"name": self.root_label, "path": "", "is_dir": True}
        self.root.label = Text(self.root_label, style="bold #22d3ee")
        self._add_children(self.root, payload.get("children", []))
        self.root.expand()
        if select:
            # Node line numbers only exist once the tree has laid out again.
            self.call_after_refresh(self.select_path, select)

    def _add_children(self, parent: TreeNode[dict], children: list[dict]) -> None:
        for child in children:
            expanded = child["path"] in self._expanded
            if child["is_dir"]:
                node = parent.add(_label(child, expanded), data=child, expand=expanded)
                self._add_children(node, child.get("children", []))
            else:
                parent.add_leaf(_label(child), data=child)

    def _walk(self, node: TreeNode[dict] | None = None):
        node = node or self.root
        yield node
        for child in node.children:
            yield from self._walk(child)

    def select_path(self, path: str) -> bool:
        for node in self._walk():
            if node.data and node.data.get("path") == path:
                self._expand_ancestors(node)
                self.select_node(node)
                self.scroll_to_node(node, animate=False)
                return True
        return False

    def _expand_ancestors(self, node: TreeNode[dict]) -> None:
        parent = node.parent
        while parent is not None:
            parent.expand()
            parent = parent.parent

    # -- current selection -------------------------------------------------
    @property
    def selected(self) -> dict[str, Any]:
        node = self.cursor_node
        if node is None or node.data is None:
            return {"name": self.root_label, "path": "", "is_dir": True}
        return node.data

    @property
    def selected_dir(self) -> str:
        """The folder a new item should be created in."""
        data = self.selected
        if data["is_dir"]:
            return data["path"]
        parent = data["path"].rsplit("/", 1)
        return parent[0] if len(parent) > 1 else ""

    # -- events ------------------------------------------------------------
    def on_tree_node_expanded(self, event: Tree.NodeExpanded[dict]) -> None:
        if event.node.data:
            path = event.node.data["path"]
            self._expanded.add(path)
            if event.node is not self.root:
                event.node.label = _label(event.node.data, expanded=True)

    def on_tree_node_collapsed(self, event: Tree.NodeCollapsed[dict]) -> None:
        if event.node.data:
            self._expanded.discard(event.node.data["path"])
            if event.node is not self.root:
                event.node.label = _label(event.node.data, expanded=False)

    def on_tree_node_selected(self, event: Tree.NodeSelected[dict]) -> None:
        data = event.node.data
        if data and not data["is_dir"]:
            self.post_message(self.NoteSelected(data["path"]))

    # -- actions -----------------------------------------------------------
    def action_new_note(self) -> None:
        self.post_message(self.NewNoteRequested(self.selected_dir))

    def action_new_folder(self) -> None:
        self.post_message(self.NewFolderRequested(self.selected_dir))

    def action_rename(self) -> None:
        data = self.selected
        if data["path"]:
            self.post_message(self.RenameRequested(data["path"], data["is_dir"]))

    def action_delete(self) -> None:
        data = self.selected
        if data["path"]:
            self.post_message(self.DeleteRequested(data["path"], data["is_dir"]))

    def action_search(self) -> None:
        self.post_message(self.SearchRequested())

    def action_reload(self) -> None:
        self.post_message(self.ReloadRequested())
