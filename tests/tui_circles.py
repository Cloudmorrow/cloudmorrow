"""The circles half of the fake server the TUI tests drive (docs/CIRCLES.md).

Members, with everything and everybody in it, as a fresh server has; a test
that wants Kids or somebody adrift reshapes `circle_list` before it opens the
panel. Every change is kept in `circle_calls`, and made, the way the real
store makes it, so a table drawn again shows it.
"""

from __future__ import annotations

import copy

from cloudmorrow.client.api import ApiError


def circle_row(name: str, rules: dict | None = None, members: list | None = None, **extra) -> dict:
    return {
        "id": name.lower(),
        "name": name,
        "default": False,
        "rules": dict(rules or {}),
        "members": sorted(members or []),
        **extra,
    }


class FakeCircles:
    """Mixed into FakeClient; asks `user_list` who is on the server."""

    def setup_circles(self) -> None:
        self.circle_list: list[dict] = [circle_row("Members", {"*": "write"}, ["bram", "guest"], default=True)]
        self.circle_calls: list[tuple] = []

    def _circle(self, key: str) -> dict:
        for circle in self.circle_list:
            if key.lower() in (circle["id"], circle["name"].lower()):
                return circle
        raise ApiError(f"no circle called {key}", status_code=404)

    async def circles(self) -> list[dict]:
        return copy.deepcopy(self.circle_list)

    async def create_circle(self, name: str, *, rules=None, members=None) -> dict:
        self.circle_calls.append(("create", name))
        if any(c["name"].lower() == name.lower() for c in self.circle_list):
            raise ApiError(f"there is already a circle called {name}", status_code=400)
        circle = circle_row(name, rules, members)
        self.circle_list.append(circle)
        self.circle_list.sort(key=lambda c: c["name"].lower())
        return copy.deepcopy(circle)

    async def update_circle(self, circle: str, **fields: object) -> dict:
        self.circle_calls.append(("update", circle, fields))
        found = self._circle(circle)
        if fields.get("name"):
            found["name"] = fields["name"]
        if fields.get("rules") is not None:
            found["rules"] = dict(fields["rules"])
        if fields.get("default") is not None:
            found["default"] = bool(fields["default"])
        return copy.deepcopy(found)

    async def set_circle_rule(self, circle: str, model: str, access: str) -> dict:
        self.circle_calls.append(("rule", circle, model, access))
        found = self._circle(circle)
        if model == "*" and access == "none":
            found["rules"].pop("*", None)
        else:
            found["rules"][model] = access
        return copy.deepcopy(found)

    async def delete_circle(self, circle: str) -> None:
        self.circle_calls.append(("delete", circle))
        found = self._circle(circle)
        self.circle_list = [c for c in self.circle_list if c is not found]

    async def join_circle(self, circle: str, username: str) -> dict:
        self.circle_calls.append(("join", circle, username))
        if not any(u["username"] == username for u in self.user_list):
            raise ApiError(f"there is nobody called {username} on this server", status_code=400)
        found = self._circle(circle)
        found["members"] = sorted(set(found["members"]) | {username})
        return copy.deepcopy(found)

    async def leave_circle(self, circle: str, username: str) -> dict:
        self.circle_calls.append(("leave", circle, username))
        found = self._circle(circle)
        found["members"] = [m for m in found["members"] if m != username]
        return copy.deepcopy(found)
