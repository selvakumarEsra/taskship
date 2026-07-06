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
class NodeDecision:
    """One node's reconciliation outcome, for review and dry-run output."""

    external_id: str
    action: str   # "create" | "update" | "skip" | "orphan"
    reason: str


@dataclass
class SyncReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    orphaned: list[str] = field(default_factory=list)
    decisions: list[NodeDecision] = field(default_factory=list)
    dry_run: bool = False

    def _decide(self, external_id: str, action: str, reason: str) -> None:
        self.decisions.append(NodeDecision(external_id, action, reason))
        getattr(self, {"create": "created", "update": "updated",
                       "skip": "skipped", "orphan": "orphaned"}[action]).append(external_id)

    def as_dict(self) -> dict:
        return {
            "dry_run": self.dry_run,
            "created": list(self.created),
            "updated": list(self.updated),
            "skipped": list(self.skipped),
            "orphaned": list(self.orphaned),
            "decisions": [
                {"id": d.external_id, "action": d.action, "reason": d.reason}
                for d in self.decisions
            ],
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
    report = SyncReport(dry_run=dry_run)
    payloads = build_payloads(plan, templates_dir)
    known_before = state.known_ids()

    for payload in payloads:
        key = _resolve_key(payload, client, state)

        if key is None:
            parent_key = (
                state.key(payload.parent_external_id)
                if payload.parent_external_id else None
            )
            report._decide(payload.external_id, "create", "no existing Jira issue")
            if not dry_run:
                key = client.create(payload, parent_key)
                state.record(payload.external_id, key, payload.content_hash,
                             payload.field_hashes)
            continue

        entry = state.entry(payload.external_id)
        if entry is None:
            report._decide(payload.external_id, "update",
                           "recovered via watermark; re-asserting desired state")
        elif entry.hash != payload.content_hash:
            report._decide(payload.external_id, "update", "content changed")
        else:
            report._decide(payload.external_id, "skip", "unchanged")
            continue

        if not dry_run:
            client.update(key, _changed_fields(payload, entry))
            state.record(payload.external_id, key, payload.content_hash,
                         payload.field_hashes)

    _flag_orphans(known_before, payloads, client, state, report, dry_run)

    if not dry_run:
        state.save()
    return report


ORPHAN_LABEL = "taskship:orphaned"


def _flag_orphans(known_before, payloads, client, state, report, dry_run) -> None:
    """Flag nodes dropped from the plan; never delete them (REQ-TS-008).

    @implements REQ-TS-008

    A node in state but no longer in the plan is labelled ``taskship:orphaned``
    and reported for a human to resolve, then dropped from state so it is not
    re-flagged on every subsequent sync.
    """
    present = {p.external_id for p in payloads}
    for ext_id in sorted(known_before - present):
        key = state.key(ext_id)
        report._decide(ext_id, "orphan",
                       "removed from plan; flagged taskship:orphaned for a human")
        if not dry_run:
            if key is not None:
                client.add_label(key, ORPHAN_LABEL)
            state.drop(ext_id)


def _changed_fields(payload: NodePayload, entry) -> dict:
    """The subset of managed fields whose per-field hash changed (A3)."""
    prev = entry.fields if entry else {}
    return {
        name: payload.fields[name]
        for name, h in payload.field_hashes.items()
        if prev.get(name) != h
    }
