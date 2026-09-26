"""Administration → Quills → Running: what a Quill's code is doing on this server.

For the Quill under the cursor: each service with its state (running,
restarting, stopped), since when, how it last exited, and the last lines of
its log; each `run` job and when it last ran; each webhook's address with its
secret, to paste into whatever sends it; and who all of it runs as.

The buttons are the three things an administrator does to running code:
restart it, give it a new token (the old one stops working at once, and the
services restart with the new), and give its webhooks new secrets (whatever
sends them needs the new address). Copy puts every webhook's address, secret
included, on the clipboard.
"""

from __future__ import annotations

from rich.markup import escape
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Label, Static

from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.screens.modals import Modal
from cloudmorrow.tui.theme import ACCENT, BAD, GOOD, MUTED, WARN

STATE_COLOUR = {"running": GOOD, "restarting": WARN, "stopped": MUTED}


def hook_address(hook: dict) -> str:
    """A webhook's address with its secret in it: what a sender is given."""
    return f"{hook['url']}?token={hook['secret']}"


def services_text(row: dict, logs: dict[str, list[str]] | None = None) -> str:
    """One Quill's running code, as markup; apart from the dialog, for a test to read."""
    lines = [f"[b]{escape(row.get('name') or row['id'])}[/]"]
    who = row.get("runs_as") or "nobody: reinstall it to run it as you"
    reach = ", ".join(row.get("reach") or []) or "nothing"
    lines.append(f"[{MUTED}]runs as[/] {escape(who)}[{MUTED}], and can read and write only:[/] {reach}")
    if not row.get("enabled", True):
        lines.append(f"[{WARN}]Switched off on this server: nothing of it runs.[/]")
    token = row.get("token") or {}
    if token:
        used = token.get("last_used_at") or "not yet"
        lines.append(f"[{MUTED}]token issued {token.get('issued_at', '')}, last used {used}[/]")

    for service in row.get("services") or []:
        state = service.get("state", "stopped")
        colour = STATE_COLOUR.get(state, MUTED)
        head = f"[b]{escape(service['id'])}[/]  [{colour}]{state}[/] [{MUTED}]since {service.get('since', '')}[/]"
        lines += ["", f"[b {ACCENT}]Service[/] {head}"]
        lines.append(f"  [{MUTED}]{escape(' '.join(service.get('command') or []))}[/]")
        if service.get("scheduled"):
            lines.append(f"  [{MUTED}]started by its job, not kept up[/]")
        if service.get("problem"):
            lines.append(f"  [{WARN}]{escape(service['problem'])}[/]")
        if service.get("last_exit") is not None:
            code = service["last_exit"]
            lines.append(
                f"  [{MUTED}]last exit[/] [{GOOD if code == 0 else BAD}]{code}[/]"
                f" [{MUTED}]{service.get('last_exit_at', '')}, restarts {service.get('restarts', 0)}[/]"
            )
        tail = (logs or {}).get(service["id"], service.get("log") or [])
        for line in tail[-12:]:
            lines.append(f"  [{MUTED}]│[/] {escape(line)}")

    for job in row.get("jobs") or []:
        when = job.get("last_started") or "never yet"
        running = "  [b]running now[/]" if job.get("running") else ""
        exit_ = "" if job.get("last_exit") is None else f", exit {job['last_exit']}"
        lines += ["", f"[b {ACCENT}]Job[/] [b]{escape(job['id'])}[/] "
                      f"[{MUTED}]runs {escape(job['service'])} every {job['every']}; last {when}{exit_}[/]{running}"]

    hooks = row.get("webhooks") or []
    if hooks:
        lines += ["", f"[b {ACCENT}]Webhooks[/] [{MUTED}]give the sender the whole address[/]"]
        for hook in hooks:
            what = f"makes a {hook['model']}" if hook.get("model") else f"goes to {hook.get('forward')}"
            signed = f", or signed in {hook['signature']}" if hook.get("signature") else ""
            lines.append(f"  [b]{escape(hook['id'])}[/] [{MUTED}]{escape(what)}{escape(signed)}[/]")
            lines.append(f"    {escape(hook_address(hook))}")
    return "\n".join(lines)


class QuillServicesModal(Modal[None]):
    """One Quill's running code, with restart, a new token, new secrets and copy."""

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, row: dict) -> None:
        super().__init__()
        self.row = row

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal modal-wide", id="quill-services"):
            yield Label(f"What {self.row.get('name') or self.row['id']} runs", classes="modal-title")
            with VerticalScroll(id="quill-services-body"):
                yield Static(services_text(self.row), id="quill-services-text")
            with Horizontal(classes="modal-buttons"):
                yield Button("Restart", id="restart")
                yield Button("New token", id="token")
                if self.row.get("webhooks"):
                    yield Button("New secrets", id="secrets")
                    yield Button("Copy addresses", id="copy")
                yield Button("Close", id="close")

    def on_mount(self) -> None:
        self.query_one("#close", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        button = event.button.id
        if button == "close":
            self.dismiss(None)
        elif button == "copy":
            self.app.copy_to_clipboard(
                "\n".join(hook_address(h) for h in self.row.get("webhooks") or [])
            )
            self.notify("Copied every webhook's address, secret included.")
        else:
            self.act(button or "")

    def action_close(self) -> None:
        self.dismiss(None)

    @work(exclusive=True, group="quill-services")
    async def act(self, what: str) -> None:
        api = self.app.client
        quill = self.row["id"]
        try:
            if what == "restart":
                await api.restart_quill(quill)
                said = "Restarting its services."
            elif what == "token":
                await api.rotate_quill_token(quill)
                said = "New token: the old one no longer works, and its services restart."
            else:
                for hook in self.row.get("webhooks") or []:
                    await api.rotate_webhook_secret(quill, hook["id"])
                said = "New secrets: give each sender its new address."
            rows = await api.quill_services()
        except ApiError as exc:
            self.notify(str(exc), severity="error")
            return
        self.row = next((r for r in rows if r["id"] == quill), self.row)
        self.query_one("#quill-services-text", Static).update(services_text(self.row))
        self.notify(said)
