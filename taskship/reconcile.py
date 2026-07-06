"""Idempotent reconciliation: plan → Jira, create/update/skip (REQ-TS-005).

For each node, in parents-first order, decide exactly one of:

- **create** — no Jira issue is known (state miss, and no watermark recovery);
- **update** — the issue exists but the node's content hash changed, patching
  only the fields whose per-field hash changed (A3);
- **skip** — the content hash is unchanged, so no API call is made (A2).

Because payloads are parents-first (:func:`build_payloads`), a parent is always
created before its child, so the child's ``parent`` link resolves to a real key
(A4).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol, Union

from .model import Plan
from .payload import NodePayload, build_payloads
from .state import StateStore


class JiraClient(Protocol):
    """The Jira operations the reconciler depends on (see taskship/jira.py)."""

    def create(self, payload: NodePayload, parent_key: Optional[str]) -> str: ...
    def update(self, key: str, changed_fields: dict) -> None: ...
    def add_label(self, key: str, label: str) -> None: ...
    def search_by_external_id(self, external_id: str) -> Optional[str]: ...


@dataclass
class SyncReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    orphaned: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "created": list(self.created),
            "updated": list(self.updated),
            "skipped": list(self.skipped),
            "orphaned": list(self.orphaned),
        }


def _resolve_key(payload: NodePayload, client: JiraClient, state: StateStore) -> Optional[str]:
    """Find the node's Jira key: state first, then watermark recovery (REQ-TS-006)."""
    key = state.key(payload.external_id)
    if key is not None:
        return key
    return client.search_by_external_id(payload.external_id)


def reconcile(
    plan: Plan,
    client: JiraClient,
    state: StateStore,
    dry_run: bool = False,
    templates_dir: Optional[Union[str, Path]] = None,
) -> SyncReport:
    """Reconcile the plan into Jira idempotently.

    @implements REQ-TS-005
    """
    report = SyncReport()
    payloads = build_payloads(plan, templates_dir)

    for payload in payloads:
        key = _resolve_key(payload, client, state)

        if key is None:
            parent_key = (
                state.key(payload.parent_external_id)
                if payload.parent_external_id else None
            )
            report.created.append(payload.external_id)
            if not dry_run:
                key = client.create(payload, parent_key)
                state.record(payload.external_id, key, payload.content_hash,
                             payload.field_hashes)
            continue

        entry = state.entry(payload.external_id)
        if entry is None or entry.hash != payload.content_hash:
            report.updated.append(payload.external_id)
            if not dry_run:
                changed = _changed_fields(payload, entry)
                client.update(key, changed)
                state.record(payload.external_id, key, payload.content_hash,
                             payload.field_hashes)
        else:
            report.skipped.append(payload.external_id)

    if not dry_run:
        state.save()
    return report


def _changed_fields(payload: NodePayload, entry) -> dict:
    """The subset of managed fields whose per-field hash changed (A3)."""
    prev = entry.fields if entry else {}
    return {
        name: payload.fields[name]
        for name, h in payload.field_hashes.items()
        if prev.get(name) != h
    }
