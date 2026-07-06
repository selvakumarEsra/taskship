"""Reverse sync: live board state paired with the plan (REQ-TS-010).

Reads each mapped issue's current status, assignee, and story points back from
Jira and pairs them with the planned node, producing a plan-vs-reality view.
This is strictly read-only with respect to ``plan.yaml`` — it annotates, it
never rewrites authored intent.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from .identity import iter_nodes
from .model import Plan
from .state import StateStore


class BoardReader(Protocol):
    def get_board_status(self, keys: list[str]) -> dict[str, dict]: ...


@dataclass
class StatusRow:
    external_id: str
    title: str
    level: int
    jira: Optional[str]
    status: Optional[str]
    assignee: Optional[str]
    story_points: Optional[object]


def build_status_view(plan: Plan, client: BoardReader, state: StateStore) -> list[StatusRow]:
    """Pair every plan node with its live board state (read-only).

    @implements REQ-TS-010

    Nodes not yet synced (no Jira key in state) report ``None`` live fields.
    ``plan`` is only read — no field is written back to it.
    """
    nodes = list(iter_nodes(plan))
    keys = [k for k in (state.key(ext) for ext, _n, _l in nodes) if k is not None]
    board = client.get_board_status(keys) if keys else {}

    rows: list[StatusRow] = []
    for ext_id, node, level in nodes:
        key = state.key(ext_id)
        live = board.get(key, {}) if key else {}
        rows.append(StatusRow(
            external_id=ext_id,
            title=node.title,
            level=level,
            jira=key,
            status=live.get("status"),
            assignee=live.get("assignee"),
            story_points=live.get("story_points"),
        ))
    return rows
