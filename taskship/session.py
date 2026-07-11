"""In-memory plan session — the engine both front doors drive (REQ-TS-013).

A ``TaskShipSession`` holds the plan-as-code (validated model + the raw,
comment-preserving ruamel document) and exposes the operations the CLI and the
MCP tools share: read, fine-grained edits, idempotent sync, and reverse status.
Every mutation re-validates against the schema and is reverted if invalid, so an
agent can never push the plan into an invalid state. Edits go through the raw
document, so ``save()`` round-trips losslessly and the result is reviewable in
the same file a human edits.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .connect import OfflineClient, build_client
from .identity import INTAKE_EPIC_ID, INTAKE_STORY_ID, local_id
from .model import Plan
from .plan_io import dump_plan, load_plan
from .reconcile import reconcile
from .status import build_status_view
from .state import StateStore


class PlanEditError(Exception):
    """A requested edit could not be applied (bad target or invalid result)."""


class TaskShipSession:
    """Stateful plan session shared by the CLI and MCP server."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.plan_path = self.root / "plan.yaml"
        self.plan, self.raw = load_plan(self.plan_path)

    # --- read -------------------------------------------------------------

    def get_plan(self) -> dict:
        """@implements REQ-TS-013 — the current plan as a plain dict."""
        return self.plan.model_dump()

    # --- fine-grained edits ----------------------------------------------

    def add_epic(self, title: str, id: Optional[str] = None,
                 summary: Optional[str] = None) -> str:
        epic = CommentedMap()
        if id:
            epic["id"] = id
        epic["title"] = title
        if summary:
            epic["summary"] = summary
        epic["stories"] = CommentedSeq()
        self.raw.setdefault("epics", CommentedSeq()).append(epic)
        self._revalidate()
        return id or local_id(self.plan.epics[-1])

    def add_story(self, epic_id: str, title: str, id: Optional[str] = None,
                  kind: Optional[str] = None) -> str:
        epic = self._find_epic(epic_id)
        story = CommentedMap()
        if id:
            story["id"] = id
        story["title"] = title
        if kind:
            story["kind"] = kind
        story["tasks"] = CommentedSeq()
        epic.setdefault("stories", CommentedSeq()).append(story)
        self._revalidate()
        return id or title

    def add_task(self, epic_id: str, story_id: str, type: str, title: str,
                 subtype: Optional[str] = None,
                 metrics: Optional[dict] = None, id: Optional[str] = None) -> str:
        story = self._find_story(epic_id, story_id)
        task = CommentedMap()
        if id:
            task["id"] = id
        task["type"] = type
        if subtype:
            task["subtype"] = subtype
        task["title"] = title
        if metrics:
            task["metrics"] = CommentedMap(metrics)
        story.setdefault("tasks", CommentedSeq()).append(task)
        self._revalidate()
        return id or title

    def update_plan(self, patch: dict) -> dict:
        """@implements REQ-TS-013 — shallow-merge top-level plan fields."""
        for key, value in patch.items():
            self.raw[key] = value
        self._revalidate()
        return self.get_plan()

    # --- doors: ops intake + test derivation -----------------------------

    def observe(self, title: str, impact: Optional[str] = None,
                evidence: Optional[str] = None,
                action: Optional[str] = None) -> dict:
        """Append one ops-observation task to the intake lane, plan-only.

        @implements REQ-DOORS-002

        Creates the ``ops-intake`` epic + ``kind: ops`` story on first use
        without touching any existing node. Each call appends a distinct task
        with a unique id (observations are events, not idempotent nodes), so a
        later sync never collides. Makes no Jira calls. On an invalid result the
        edit is reverted (``PlanValidationError``) and nothing is written.
        """
        story, lane_created = self._ensure_intake_lane()
        obs_id = f"obs-{uuid.uuid4().hex[:8]}"
        task = CommentedMap()
        task["id"] = obs_id
        task["type"] = "ops-observation"
        task["title"] = title
        fields = CommentedMap()
        fields["observation"] = title
        if impact:
            fields["impact"] = impact
        if evidence:
            fields["evidence"] = evidence
        if action:
            fields["suggested_action"] = action
        task["fields"] = fields
        story.setdefault("tasks", CommentedSeq()).append(task)
        self._revalidate()
        qid = f"{INTAKE_EPIC_ID}/{INTAKE_STORY_ID}/{obs_id}"
        return {"added": [qid], "id": obs_id, "lane_created": lane_created}

    def derive_testplan(self) -> dict:
        """Ensure one e2e test-case task per non-ops story, idempotently.

        @implements REQ-DOORS-005

        For every story whose ``kind`` is not ``ops``, ensures exactly one task
        of type ``test-case`` with the deterministic id ``<story-id>-e2e`` and
        ``scope`` pre-filled from the story title. Existing test-case tasks
        (even ones the test manager edited) are never modified or duplicated, so
        a re-run on an unchanged plan changes nothing. Plan-only, no Jira calls.
        Returns the qualified ids added and skipped.
        """
        added: list[str] = []
        skipped: list[str] = []
        for epic in self.raw.get("epics", []):
            eid = _node_id(epic)
            for story in epic.get("stories", []):
                if story.get("kind") == "ops":
                    continue
                sid = _node_id(story)
                tc_id = f"{sid}-e2e"
                qid = f"{eid}/{sid}/{tc_id}"
                tasks = story.setdefault("tasks", CommentedSeq())
                if any(_node_id(t) == tc_id for t in tasks):
                    skipped.append(qid)
                    continue
                task = CommentedMap()
                task["id"] = tc_id
                task["type"] = "test-case"
                task["title"] = f"E2E regression: {story.get('title')}"
                # Name the source story so its regression suite is one filter
                # away; merge so plan/epic default labels still cascade in.
                task["labels"] = CommentedSeq([f"taskship:story:{sid}"])
                task["labels_merge"] = True
                fields = CommentedMap()
                fields["scope"] = story.get("title")
                task["fields"] = fields
                tasks.append(task)
                added.append(qid)
        self._revalidate()
        return {"added": added, "skipped": skipped}

    def _ensure_intake_lane(self) -> tuple[CommentedMap, bool]:
        """Return the intake ``(story, lane_created)``, creating the lane once.

        @implements REQ-DOORS-002 — appends a fresh ``ops-intake`` epic with a
        ``kind: ops`` story when absent; existing nodes are left untouched.
        """
        for epic in self.raw.get("epics", []):
            if _node_id(epic) == INTAKE_EPIC_ID:
                for story in epic.get("stories", []):
                    if story.get("kind") == "ops":
                        return story, False
                story = _make_intake_story()
                epic.setdefault("stories", CommentedSeq()).append(story)
                return story, True
        story = _make_intake_story()
        epic = CommentedMap()
        epic["id"] = INTAKE_EPIC_ID
        epic["title"] = "Ops intake"
        epic["summary"] = "Production observations awaiting triage."
        epic["stories"] = CommentedSeq([story])
        self.raw.setdefault("epics", CommentedSeq()).append(epic)
        return story, True

    def save(self) -> None:
        dump_plan(self.raw, self.plan_path)

    # --- sync / status ----------------------------------------------------

    def sync_to_jira(self, dry_run: bool = False, client=None) -> dict:
        """@implements REQ-TS-013 — reconcile the plan; returns the diff."""
        state = StateStore(self.root / ".taskship" / "state.json")
        if client is None:
            client = OfflineClient() if dry_run else build_client(self.plan.jira_project)
        report = reconcile(self.plan, client, state, dry_run=dry_run,
                           templates_dir=self._templates_dir())
        return report.as_dict()

    def get_board_status(self, client=None) -> list[dict]:
        """@implements REQ-TS-013 — reverse-sync view as plain dicts."""
        state = StateStore(self.root / ".taskship" / "state.json")
        if client is None:
            client = build_client(self.plan.jira_project)
        rows = build_status_view(self.plan, client, state)
        return [
            {"external_id": r.external_id, "title": r.title, "level": r.level,
             "jira": r.jira, "status": r.status, "assignee": r.assignee,
             "story_points": r.story_points}
            for r in rows
        ]

    # --- internals --------------------------------------------------------

    def _templates_dir(self) -> Optional[Path]:
        d = self.root / "templates"
        return d if d.is_dir() else None

    def _revalidate(self) -> None:
        """Re-parse the raw doc; on failure revert so state stays valid."""
        snapshot = self.plan
        try:
            self.plan = Plan.from_mapping(self.raw)
        except Exception:
            # Reload the raw doc from the last-good model to drop the bad edit.
            self.raw = _to_commented(snapshot.model_dump())
            self.plan = snapshot
            raise

    def _find_epic(self, epic_id: str) -> CommentedMap:
        for epic in self.raw.get("epics", []):
            if _node_id(epic) == epic_id:
                return epic
        raise PlanEditError(f"no epic with id '{epic_id}'")

    def _find_story(self, epic_id: str, story_id: str) -> CommentedMap:
        for story in self._find_epic(epic_id).get("stories", []):
            if _node_id(story) == story_id:
                return story
        raise PlanEditError(f"no story '{story_id}' under epic '{epic_id}'")


def _node_id(node: dict) -> str:
    from .identity import slug
    return node.get("id") or slug(node.get("title", ""))


def _make_intake_story() -> CommentedMap:
    """A fresh ``kind: ops`` story to hold observations (REQ-DOORS-002)."""
    story = CommentedMap()
    story["id"] = INTAKE_STORY_ID
    story["title"] = "Production observations"
    story["kind"] = "ops"
    story["tasks"] = CommentedSeq()
    return story


def _to_commented(data: dict):
    """Best-effort convert a plain dict back into ruamel structures."""
    if isinstance(data, dict):
        m = CommentedMap()
        for k, v in data.items():
            if v is not None:
                m[k] = _to_commented(v)
        return m
    if isinstance(data, list):
        s = CommentedSeq()
        for item in data:
            s.append(_to_commented(item))
        return s
    return data
