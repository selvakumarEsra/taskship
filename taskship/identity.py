"""Stable local identity for plan nodes (REQ-TS-002).

Every epic, story, and task has a *local id* that is the stable identity
TaskShip tracks — not the Jira key. The local id is the author-supplied ``id``
when present, otherwise a deterministic slug of the node's ``title``. Because
identity is pinned to the id (not the title), an author can rename a node's
title without changing its identity or causing a duplicate on the next sync.

The *qualified id* is the ``/``-joined path of local ids from the epic down to
the node (e.g. ``guest-checkout/guest-flow/biz-spec``). Qualifying by parent
path guarantees two nodes that share a title under different parents resolve to
distinct ids, so titles need not be globally unique.
"""
from __future__ import annotations

import re
from typing import Iterator, Union

from .model import Epic, Plan, Story, Task

Node = Union[Epic, Story, Task]

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slug(text: str) -> str:
    """Deterministically kebab-case ``text``.

    Lowercase, replace every run of non-alphanumerics with a single ``-``, and
    trim leading/trailing dashes. Pure and stable: identical input always yields
    identical output (REQ-TS-002 A3) — no randomness, no timestamps.
    """
    return _SLUG_STRIP.sub("-", text.lower()).strip("-")


def local_id(node: Node) -> str:
    """The node's stable local id: explicit ``id`` if set, else a title slug.

    @implements REQ-TS-002
    """
    if node.id:
        return node.id
    return slug(node.title)


def qualified_id(*local_ids: str) -> str:
    """Join local ids from the root down into a parent-qualified id.

    @implements REQ-TS-002
    """
    return "/".join(local_ids)


def iter_nodes(plan: Plan) -> Iterator[tuple[str, Node, int]]:
    """Walk the plan yielding ``(qualified_id, node, level)`` parents-first.

    @implements REQ-TS-002

    ``level`` mirrors the Jira hierarchy: ``1`` epic, ``0`` story/task. Parents
    are always yielded before their children, which is also the order the
    reconciler needs so parent links resolve (see REQ-TS-005).
    """
    for epic in plan.epics:
        eid = local_id(epic)
        yield qualified_id(eid), epic, 1
        for story in epic.stories:
            sid = local_id(story)
            story_qid = qualified_id(eid, sid)
            yield story_qid, story, 0
            for task in story.tasks:
                tid = local_id(task)
                yield qualified_id(eid, sid, tid), task, 0
