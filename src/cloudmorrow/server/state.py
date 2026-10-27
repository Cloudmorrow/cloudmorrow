"""Everything the server holds while it runs: its config and its stores.

Built once by the app factory (app.py) and handed to routes through
`deps.get_state`, and to the parts that are not routes (MCP tools, Quill
code, space notices) directly. It depends on no web framework, so a store
can take it without pulling in the HTTP layer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cloudmorrow.server.agents import AgentStore, JobStore
from cloudmorrow.server.circles import CircleStore
from cloudmorrow.server.config import ServerConfig
from cloudmorrow.server.database import Database
from cloudmorrow.server.db import UserStore
from cloudmorrow.server.features import FeatureStore
from cloudmorrow.server.mcp import MCPStore
from cloudmorrow.server.notifications import NotificationStore
from cloudmorrow.server.quills import QuillRegistry
from cloudmorrow.server.quills.services import Supervisor
from cloudmorrow.server.quills.sharing import Policy, SharingStore
from cloudmorrow.server.quills.shelf import Shelf
from cloudmorrow.server.quills.tokens import QuillTokenStore
from cloudmorrow.server.records import RecordStore
from cloudmorrow.server.sealed import Sealer
from cloudmorrow.server.secrets import SecretStore
from cloudmorrow.server.settings import SettingsStore
from cloudmorrow.server.shares import ShareStore
from cloudmorrow.server.syncs import SyncStore
from cloudmorrow.server.today import Weather
from cloudmorrow.server.webpush import PushStore

if TYPE_CHECKING:
    from cloudmorrow.server.access_lan import LanAnnouncer
    from cloudmorrow.server.approvals import Approvals
    from cloudmorrow.server.backups import Backups
    from cloudmorrow.server.changefeed import ChangeFeed
    from cloudmorrow.server.flows import FlowRunner
    from cloudmorrow.server.roles import RoleStore
    from cloudmorrow.server.snapshots import SnapshotStore


@dataclass(slots=True)
class AppState:
    config: ServerConfig
    # The database every store below keeps its rows in (database/).
    db: Database
    users: UserStore
    agents: AgentStore
    jobs: JobStore
    # Local backups: folders on people's machines their agents copy into My Files (syncs.py).
    syncs: SyncStore
    secrets: SecretStore
    notifications: NotificationStore
    features: FeatureStore
    shares: ShareStore
    push: PushStore
    # The assistants people have let in over MCP, and their tokens.
    mcp: MCPStore
    # The forecast for the place in the config, for the app's front page.
    weather: Weather
    # Is this a good username and password, or token, for an account? What
    # the WebDAV side asks on every request.
    credential_check: Callable[[str, str], bool]
    # What seals content at rest: the notes stores are handed it; the
    # database stores find it through their connection.
    sealer: Sealer
    # What somebody told the server about itself from the app: its name.
    settings: SettingsStore
    # The installed Quills and datamodels, and the records of every one.
    quills: QuillRegistry
    records: RecordStore
    # A Quill's credentials, and what runs its code (quills.tokens, quills.services).
    quill_tokens: QuillTokenStore | None = None
    services: Supervisor | None = None
    # Who may use which datamodels (circles.py). The record store asks it too.
    circles: CircleStore | None = None
    # What runs a Quill's Python, in its sandbox (quills/code.py).
    code: object | None = None
    # Quills of people's own: who has which, who was offered which, what was
    # asked for, and what the server allows (quills/shelf.py, quills/sharing.py).
    sharing: SharingStore | None = None
    shelf: Shelf | None = None
    policy: Policy | None = None
    # What announces the box on the home network (access_lan); None when off.
    lan: LanAnnouncer | None = None
    # What tells an open screen a record changed, as it does (changefeed.py).
    changes: ChangeFeed | None = None
    # Frozen copies of a space's records, and the signed word on them (snapshots.py).
    snapshots: SnapshotStore | None = None
    # Who holds which role (roles.py), the approvals asked of them
    # (approvals.py), and the flows that run when things happen (flows.py).
    roles: RoleStore | None = None
    approvals: Approvals | None = None
    flows: FlowRunner | None = None
    # Copies of everything into a bucket, daily, and back (backups.py).
    backups: Backups | None = None
    # The last look at the remote for newer releases, and when (routes/server.py).
    update_check: tuple[float, object] | None = None

    def cloud_name(self) -> str:
        """What this cloud is called: set from the app, else from the config."""
        return self.settings.name(self.config.name)

    def weather_place(self) -> str:
        """Where the front page's weather is for: set from the app, else from the config."""
        return self.settings.weather_place(self.config.weather_place)

    def ensure_drive(self, username: str) -> None:
        """The person's own drive, with its Notes folder, exists the moment they do."""
        self.config.notes_root(username).mkdir(parents=True, exist_ok=True)
