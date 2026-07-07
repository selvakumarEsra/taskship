"""Field cascade: defaults → epic → story → task (REQ-TS-003).

Fields defined at a broader scope are inherited by narrower scopes, and a
narrower scope may override them. A node that does not specify a cascadeable
field inherits the resolved value from its parent (the plan ``defaults`` at the
root). A node that *does* specify the field overrides the inherited value
(replace, not union) — unless it opts into merge, which unions its value with
the inherited one.

:func:`resolve_plan` returns the post-cascade field set for every node keyed by
qualified id, so a reviewer can inspect exactly what each node carries into Jira.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .identity import local_id, qualified_id
from .model import Plan


@dataclass(frozen=True)
class ResolvedFields:
    """The effective, post-cascade fields for one node (REQ-TS-003 A3)."""

    labels: list[str]
    assignee: Optional[str] = None
    sprint: Optional[str] = None


def effective_scalar(inherited: Optional[str], value: Optional[str]) -> Optional[str]:
    """Resolve a scalar cascade field: the node's value, else the inherited one.

    @implements REQ-DEL-001

    Unlike labels there is no merge — a narrower scope either overrides
    (``value`` is set) or inherits (``value is None``).
    """
    return value if value is not None else inherited


def effective_labels(
    inherited: list[str], node_labels: Optional[list[str]], merge: bool
) -> list[str]:
    """Resolve a node's labels against the inherited set.

    @implements REQ-TS-003

    - ``node_labels is None`` → inherit the parent's resolved labels.
    - override (default) → the node's own labels, exactly (A2).
    - merge (opt-in) → inherited unioned with the node's, order-preserving,
      de-duplicated.
    """
    if node_labels is None:
        return list(inherited)
    if not merge:
        return list(node_labels)
    merged = list(inherited)
    for label in node_labels:
        if label not in merged:
            merged.append(label)
    return merged


def resolve_plan(plan: Plan) -> dict[str, ResolvedFields]:
    """Compute resolved fields for every node, keyed by qualified id.

    @implements REQ-TS-003

    Walks defaults → epic → story → task, threading each level's resolved
    values down to its children.
    """
    resolved: dict[str, ResolvedFields] = {}
    root_labels = list(plan.defaults.labels)
    root_assignee = plan.defaults.assignee
    root_sprint = plan.defaults.sprint

    for epic in plan.epics:
        eid = local_id(epic)
        epic_labels = effective_labels(root_labels, epic.labels, epic.labels_merge)
        epic_assignee = effective_scalar(root_assignee, epic.assignee)
        epic_sprint = effective_scalar(root_sprint, epic.sprint)
        resolved[qualified_id(eid)] = ResolvedFields(
            labels=epic_labels, assignee=epic_assignee, sprint=epic_sprint
        )

        for story in epic.stories:
            sid = local_id(story)
            story_qid = qualified_id(eid, sid)
            story_labels = effective_labels(
                epic_labels, story.labels, story.labels_merge
            )
            story_assignee = effective_scalar(epic_assignee, story.assignee)
            story_sprint = effective_scalar(epic_sprint, story.sprint)
            resolved[story_qid] = ResolvedFields(
                labels=story_labels, assignee=story_assignee, sprint=story_sprint
            )

            for task in story.tasks:
                tid = local_id(task)
                task_labels = effective_labels(
                    story_labels, task.labels, task.labels_merge
                )
                resolved[qualified_id(eid, sid, tid)] = ResolvedFields(
                    labels=task_labels,
                    assignee=effective_scalar(story_assignee, task.assignee),
                    sprint=effective_scalar(story_sprint, task.sprint),
                )

    return resolved
