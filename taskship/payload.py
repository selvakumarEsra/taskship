"""Desired Jira state per node — the payloads the reconciler diffs (REQ-TS-005).

Turns a validated, cascade-resolved plan into a parents-first list of
:class:`NodePayload` objects: the summary, issue type, description (ADF, for
tasks), labels (resolved + type + external-id watermark), and parent external
id each node should have in Jira. Each payload carries an overall content hash
(create/update/skip decision) and per-field hashes (so an update patches only
what changed).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from .cascade import resolve_plan
from .identity import iter_nodes, local_id, qualified_id
from .model import Epic, Plan, Story, Task
from .templates import render_adf, render_labels

# Jira issue-type hierarchy: Epic (level 1), Story/Task (level 0).
_ISSUE_TYPE = {"epic": "Epic", "story": "Story", "task": "Task"}


def watermark_label(external_id: str) -> str:
    """The external-id watermark label recovery searches on (REQ-TS-006)."""
    return f"taskship:{external_id}"


def _field_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:12]


@dataclass
class NodePayload:
    external_id: str
    issue_type: str
    summary: str
    labels: list[str]
    parent_external_id: Optional[str]
    description: Optional[dict]  # ADF; tasks only
    assignee: Optional[str] = None   # REQ-DEL-001
    sprint: Optional[str] = None     # REQ-DEL-002
    fields: dict[str, object] = field(default_factory=dict)
    field_hashes: dict[str, str] = field(default_factory=dict)
    content_hash: str = ""

    def __post_init__(self) -> None:
        # The managed fields whose per-field hash drives targeted patching.
        self.fields = {"summary": self.summary, "labels": sorted(self.labels)}
        if self.description is not None:
            self.fields["description"] = self.description
        if self.assignee is not None:
            self.fields["assignee"] = self.assignee
        if self.sprint is not None:
            self.fields["sprint"] = self.sprint
        self.field_hashes = {k: _field_hash(v) for k, v in self.fields.items()}
        # Overall hash also folds in structural fields that aren't patch-diffed.
        self.content_hash = _field_hash({
            "issue_type": self.issue_type,
            "parent": self.parent_external_id,
            **self.field_hashes,
        })


def build_payloads(
    plan: Plan, templates_dir: Optional[Union[str, Path]] = None
) -> list[NodePayload]:
    """Build parents-first payloads for every node in the plan.

    @implements REQ-TS-005
    """
    resolved = resolve_plan(plan)
    payloads: list[NodePayload] = []

    for ext_id, node, _level in iter_nodes(plan):
        labels = list(resolved[ext_id].labels)
        labels.append(watermark_label(ext_id))
        parent = _parent_external_id(ext_id)

        if isinstance(node, Task):
            labels.extend(render_labels(node, templates_dir))
            # Story containment isn't expressible via Jira's parent (task
            # parents to the epic) — carry it as a filterable label instead.
            story_path = ext_id.rsplit("/", 1)[0]
            labels.append(f"taskship:story:{story_path}")
            description = render_adf(node, templates_dir)
            issue_type = _ISSUE_TYPE["task"]
        elif isinstance(node, Story):
            description = None
            issue_type = _ISSUE_TYPE["story"]
        else:  # Epic
            description = None
            issue_type = _ISSUE_TYPE["epic"]

        payloads.append(NodePayload(
            external_id=ext_id,
            issue_type=issue_type,
            summary=node.title,
            labels=_dedupe(labels),
            parent_external_id=parent,
            description=description,
            assignee=resolved[ext_id].assignee,
            sprint=resolved[ext_id].sprint,
        ))
    return payloads


def _parent_external_id(external_id: str) -> Optional[str]:
    """The Jira parent's qualified id, or None for a top-level epic.

    Jira's ``parent`` must point exactly one hierarchy level up, and Story/Task
    are both level 0 — so a task parents to its *epic*, not its story (verified
    against Jira Cloud; see TASKSHIP-DOC decisions of record). Story containment
    is carried by the watermark path and the ``taskship:story:<id>`` label.
    """
    if "/" not in external_id:
        return None
    return external_id.split("/", 1)[0]


def _dedupe(items: list[str]) -> list[str]:
    seen: list[str] = []
    for it in items:
        if it not in seen:
            seen.append(it)
    return seen
