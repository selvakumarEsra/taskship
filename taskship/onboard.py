"""Onboard an existing Jira project into plan-as-code (REQ-ONBOARD-001..005).

`taskship onboard <KEY>` is the one-time bootstrap for a team whose project
already lives in Jira (VISION-DOC decision 1). It reads every non-done epic,
story, and task in the project, builds a schema-valid ``plan.yaml`` mirroring
the Jira parent hierarchy (REQ-ONBOARD-001), records each imported issue's key
and field snapshot in ``.taskship/state.json`` so the first sync adopts rather
than duplicates (REQ-ONBOARD-002), assigns the pass-through ``imported`` type to
tasks whose type cannot be inferred so sync never rewrites their descriptions
(REQ-ONBOARD-003), refuses to run against a live plan unless ``--force`` and
writes both files only after a complete in-memory import (REQ-ONBOARD-004), and
returns a review summary for the human review that follows (REQ-ONBOARD-005).

Everything up to the two file writes is pure and in-memory: a fetch or build
failure leaves neither ``plan.yaml`` nor ``state.json`` (REQ-ONBOARD-004.A2).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from ruamel.yaml.comments import CommentedMap

from .identity import slug
from .model import Plan, PlanValidationError, Task
from .payload import build_payloads
from .plan_io import dump_plan
from .render import render_tree
from .state import StateStore
from .templates import TemplateError, render_adf

# Jira issue-type names TaskShip maps onto its epic/story/task lanes. Anything
# else (Bug, Spike, Sub-task, …) is an unrecognized type: reported as skipped
# with a count, never silently dropped (REQ-ONBOARD-001.A3).
_EPIC_TYPE = "Epic"
_STORY_TYPE = "Story"
_TASK_TYPE = "Task"
_RECOGNIZED = {_EPIC_TYPE, _STORY_TYPE, _TASK_TYPE}

# The catch-all lane orphaned issues land in rather than being dropped
# (REQ-ONBOARD-001.A3). These synthetic containers have no Jira key, so sync
# creates them on the first run — real orphaned issues nested inside keep their
# keys and are adopted like any other imported node.
CATCH_ALL_EPIC_ID = "imported-unsorted"
CATCH_ALL_EPIC_TITLE = "Imported — unsorted (review and re-home)"
ORPHAN_STORY_ID = "orphaned-tasks"
ORPHAN_STORY_TITLE = "Orphaned tasks (no parent story in Jira)"

_TYPE_LABEL_PREFIX = "taskship:type:"

_HEADER_COMMENT = (
    " Imported from Jira by `taskship onboard` — this is a DRAFT for review.\n"
    " Prune what you don't want to manage as plan-as-code, then run\n"
    " `taskship sync --dry-run` to confirm every issue is adopted (zero creates).\n"
    " After this one-time bootstrap, plan.yaml owns structure (VISION-DOC)."
)


class OnboardError(Exception):
    """Onboarding refused or could not produce a valid plan (writes nothing)."""


@dataclass
class ImportedIssue:
    """The subset of a Jira issue onboarding reads (REQ-ONBOARD-001.A1)."""

    key: str
    issue_type: str
    summary: str
    parent_key: Optional[str]
    labels: list[str]
    status: Optional[str]
    status_done: bool
    has_description: bool


@dataclass
class OnboardResult:
    """Everything the review summary reports (REQ-ONBOARD-005)."""

    project_key: str
    plan: Plan
    counts: dict[str, int]                         # epics / stories / tasks imported
    skipped: list[tuple[str, str]] = field(default_factory=list)   # (key, reason)
    done_leftovers: list[str] = field(default_factory=list)        # skipped-done keys
    empty_epics: list[str] = field(default_factory=list)           # noise: no open stories
    downgraded: list[str] = field(default_factory=list)            # kept-type → imported
    catch_all_used: bool = False
    replaced: bool = False                          # --force overwrote a live plan
    state_entries: int = 0

    @property
    def skipped_by_reason(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for _key, reason in self.skipped:
            counts[reason] = counts.get(reason, 0) + 1
        return counts


# --- parsing ---------------------------------------------------------------

def parse_issue(raw: dict) -> ImportedIssue:
    """Normalize a raw Jira issue into the fields onboarding needs."""
    f = raw.get("fields", {})
    status_field = f.get("status") or {}
    category = (status_field.get("statusCategory") or {}).get("key")
    parent = f.get("parent") or {}
    return ImportedIssue(
        key=raw["key"],
        issue_type=(f.get("issuetype") or {}).get("name", ""),
        summary=f.get("summary") or raw["key"],
        parent_key=parent.get("key"),
        labels=list(f.get("labels") or []),
        status=status_field.get("name"),
        status_done=(category == "done"),
        has_description=bool(f.get("description")),
    )


# --- type inference (REQ-ONBOARD-003.A1) -----------------------------------

def _clean_labels(labels: list[str]) -> list[str]:
    """Human labels only — TaskShip's own labels are re-derived on sync."""
    return [lbl for lbl in labels if not lbl.startswith("taskship:")]


def infer_task_type(
    labels: list[str], templates_dir: Optional[Union[str, Path]]
) -> tuple[str, bool]:
    """A task's type: a ``taskship:type:*`` label wins, else ``imported``.

    @implements REQ-ONBOARD-003

    A previously TaskShip-managed issue carries a ``taskship:type:<t>`` label and
    keeps that type (A1). Onboarding cannot recover the template ``fields`` from
    a rendered Jira description, so a kept type whose template would refuse to
    render without required fields is downgraded to the pass-through ``imported``
    type (returned flag ``True``) rather than aborting the whole import.
    """
    for lbl in labels:
        if lbl.startswith(_TYPE_LABEL_PREFIX):
            candidate = lbl[len(_TYPE_LABEL_PREFIX):]
            if not candidate or candidate == "imported":
                continue
            if _renders_empty(candidate, templates_dir):
                return candidate, False
            return "imported", True
    return "imported", False


def _renders_empty(task_type: str, templates_dir: Optional[Union[str, Path]]) -> bool:
    """Whether ``task_type`` renders with no authored fields (no required keys)."""
    probe = Task(type=task_type, title="probe")
    try:
        render_adf(probe, templates_dir)
        return True
    except TemplateError:
        return False


# --- tree building (REQ-ONBOARD-001) ---------------------------------------

def _node(local_id: str, title: str, labels: list[str], **extra) -> dict:
    node = {"id": local_id, "title": title}
    node.update(extra)
    clean = _clean_labels(labels)
    if clean:
        node["labels"] = clean
    return node


def build_plan(
    issues: list[ImportedIssue],
    project_key: str,
    templates_dir: Optional[Union[str, Path]],
) -> tuple[dict, dict[str, str], OnboardResult]:
    """Build the plan mapping, the qid→Jira-key map, and the review result.

    @implements REQ-ONBOARD-001

    Pure: builds everything in memory, mirroring Jira's parent hierarchy. Every
    node gets a pinned id derived from its Jira key (``PROJ-123`` → ``proj-123``)
    so later retitles never change identity (A2). Non-done epics/stories/tasks
    land in the tree; issues that fit no lane are routed to the catch-all epic or
    listed as skipped (A3).
    """
    epic_order: list[dict] = []
    epics_by_key: dict[str, dict] = {}
    stories_by_key: dict[str, tuple[dict, str]] = {}   # key -> (node, epic_id)
    key_by_qid: dict[str, str] = {}
    skipped: list[tuple[str, str]] = []
    done_leftovers: list[str] = []
    downgraded: list[str] = []

    catch_all_epic: dict = {"id": CATCH_ALL_EPIC_ID, "title": CATCH_ALL_EPIC_TITLE,
                            "stories": []}
    orphan_story: dict = {"id": ORPHAN_STORY_ID, "title": ORPHAN_STORY_TITLE, "tasks": []}
    catch_all_used = False

    def ensure_catch_all_epic() -> None:
        nonlocal catch_all_used
        if not catch_all_used:
            epic_order.append(catch_all_epic)
            catch_all_used = True

    def ensure_orphan_story() -> None:
        ensure_catch_all_epic()
        if orphan_story not in catch_all_epic["stories"]:
            catch_all_epic["stories"].append(orphan_story)

    # Partition once: recognized-and-open vs skipped (unrecognized / done).
    epics_open, stories_open, tasks_open = [], [], []
    for iss in issues:
        if iss.issue_type not in _RECOGNIZED:
            skipped.append((iss.key, f"unrecognized issue type: {iss.issue_type or '?'}"))
            continue
        if iss.status_done:
            skipped.append((iss.key, "done status"))
            done_leftovers.append(iss.key)
            continue
        {_EPIC_TYPE: epics_open, _STORY_TYPE: stories_open,
         _TASK_TYPE: tasks_open}[iss.issue_type].append(iss)

    # Epics.
    for iss in epics_open:
        eid = slug(iss.key)
        node = _node(eid, iss.summary, iss.labels, stories=[])
        epic_order.append(node)
        epics_by_key[iss.key] = node
        key_by_qid[eid] = iss.key

    # Stories: attach to their Jira parent epic, else the catch-all epic.
    for iss in stories_open:
        sid = slug(iss.key)
        node = _node(sid, iss.summary, iss.labels, tasks=[])
        parent_epic = epics_by_key.get(iss.parent_key)
        if parent_epic is not None:
            parent_epic["stories"].append(node)
            epic_id = parent_epic["id"]
        else:
            ensure_catch_all_epic()
            catch_all_epic["stories"].append(node)
            epic_id = CATCH_ALL_EPIC_ID
        stories_by_key[iss.key] = (node, epic_id)
        key_by_qid[f"{epic_id}/{sid}"] = iss.key

    # Tasks: attach to their Jira parent story, else the orphaned-tasks lane.
    # Jira parents a task to its epic (not its story), so a task whose parent is
    # not an imported story has no lane and is routed to the catch-all.
    for iss in tasks_open:
        tid = slug(iss.key)
        task_type, was_downgraded = infer_task_type(iss.labels, templates_dir)
        if was_downgraded:
            downgraded.append(iss.key)
        node = _node(tid, iss.summary, iss.labels, type=task_type)
        parent_story = stories_by_key.get(iss.parent_key)
        if parent_story is not None:
            story_node, epic_id = parent_story
            story_node["tasks"].append(node)
            story_id = story_node["id"]
        else:
            ensure_orphan_story()
            orphan_story["tasks"].append(node)
            epic_id, story_id = CATCH_ALL_EPIC_ID, ORPHAN_STORY_ID
        key_by_qid[f"{epic_id}/{story_id}/{tid}"] = iss.key

    plan_map = CommentedMap()
    plan_map["product"] = project_key
    plan_map["jira_project"] = project_key
    plan_map["epics"] = epic_order
    plan_map.yaml_set_start_comment(_HEADER_COMMENT)

    # Noise flag: real (non-catch-all) epics with zero open stories.
    empty_epics = [
        e["title"] for e in epic_order
        if e["id"] != CATCH_ALL_EPIC_ID and not e.get("stories")
    ]

    result = OnboardResult(
        project_key=project_key,
        plan=None,  # filled in by onboard_project after validation
        counts={"epics": len(epics_by_key),
                "stories": len(stories_by_key),
                "tasks": len(key_by_qid) - len(epics_by_key) - len(stories_by_key)},
        skipped=skipped,
        done_leftovers=done_leftovers,
        empty_epics=empty_epics,
        downgraded=downgraded,
        catch_all_used=catch_all_used,
    )
    return plan_map, key_by_qid, result


# --- the command engine ----------------------------------------------------

def onboard_project(
    client,
    project_key: str,
    root: Union[str, Path],
    *,
    force: bool = False,
    templates_dir: Optional[Union[str, Path]] = None,
) -> OnboardResult:
    """Import ``project_key`` from Jira into ``root`` as plan-as-code.

    @implements REQ-ONBOARD-001
    @implements REQ-ONBOARD-002
    @implements REQ-ONBOARD-004

    Refuses a live plan unless ``force`` (A004.1). Fetches and builds entirely in
    memory, then writes ``plan.yaml`` and ``.taskship/state.json`` only after a
    complete import, so an interrupted run leaves neither file (A004.2). Records
    each imported node's Jira key + payload hash the same way the reconciler
    computes them, so the next ``sync`` adopts rather than creates (REQ-ONBOARD-002).
    """
    root = Path(root)
    plan_path = root / "plan.yaml"
    state_path = root / ".taskship" / "state.json"

    replaced = plan_path.exists()
    if replaced and not force:
        raise OnboardError(
            f"onboarding is a one-time bootstrap and {plan_path} already exists. "
            "Re-importing from Jira would clobber the plan that now owns your "
            "structure (VISION-DOC decision 1). Pass --force to replace "
            f"{plan_path} and {state_path} with a fresh import."
        )

    # --- fetch + build: pure and in-memory (nothing written on failure) ----
    raw_issues = client.search_project_issues()
    issues = [parse_issue(raw) for raw in raw_issues]
    plan_map, key_by_qid, result = build_plan(issues, project_key, templates_dir)

    try:
        plan_obj = Plan.from_mapping(plan_map)
    except PlanValidationError as exc:
        raise OnboardError(
            f"imported project {project_key} does not form a valid plan; "
            f"nothing was written:\n{exc}"
        ) from exc

    # Compute state exactly as the reconciler will (REQ-ONBOARD-002.A2): record
    # each real node's payload hash so its first sync resolves to update/skip.
    payloads = build_payloads(plan_obj, templates_dir)
    adoptions = [
        (p.external_id, key_by_qid[p.external_id], p.content_hash, p.field_hashes)
        for p in payloads if p.external_id in key_by_qid
    ]

    # --- commit: both files, only now that the import fully succeeded ------
    root.mkdir(parents=True, exist_ok=True)
    if force and state_path.exists():
        state_path.unlink()  # a fresh bootstrap starts from empty state
    dump_plan(plan_map, plan_path)

    state = StateStore(state_path)
    for external_id, jira_key, content_hash, field_hashes in adoptions:
        state.record(external_id, jira_key, content_hash, field_hashes)
    state.save()

    result.plan = plan_obj
    result.replaced = replaced and force
    result.state_entries = len(adoptions)
    return result


# --- review summary (REQ-ONBOARD-005) --------------------------------------

def format_onboard_summary(result: OnboardResult) -> str:
    """Render the post-onboard review summary.

    @implements REQ-ONBOARD-005
    """
    c = result.counts
    lines: list[str] = []
    if result.replaced:
        lines.append(f"Replaced the existing plan.yaml with a fresh import of "
                     f"{result.project_key} (--force).")
    lines.append(
        f"Imported {c['epics']} epic(s), {c['stories']} story(ies), "
        f"{c['tasks']} task(s) from {result.project_key} "
        f"— adopted {result.state_entries} issue key(s)."
    )

    if result.skipped:
        lines.append("")
        lines.append(f"Skipped {len(result.skipped)} issue(s):")
        for reason, n in sorted(result.skipped_by_reason.items()):
            lines.append(f"  · {n:>3}  {reason}")

    lines.append("")
    lines.append(render_tree(result.plan))

    flags: list[str] = []
    if result.catch_all_used:
        flags.append(
            f"orphaned issues were routed to the '{CATCH_ALL_EPIC_TITLE}' epic — "
            "re-home or delete them"
        )
    if result.empty_epics:
        flags.append(
            "epics with zero open stories (likely done or noise): "
            + ", ".join(result.empty_epics)
        )
    if result.done_leftovers:
        flags.append(
            f"{len(result.done_leftovers)} done-status issue(s) were left out "
            "as leftovers: " + ", ".join(result.done_leftovers)
        )
    if result.downgraded:
        flags.append(
            f"{len(result.downgraded)} task(s) kept a type whose template needs "
            "fields we can't recover — imported as pass-through 'imported': "
            + ", ".join(result.downgraded)
        )
    if flags:
        lines.append("")
        lines.append("LIKELY NOISE — prune these first:")
        for f in flags:
            lines.append(f"  ! {f}")

    lines.append("")
    lines.append("Next steps:")
    lines.append("  1. Review and prune plan.yaml — delete what you won't manage here.")
    lines.append("  2. Run `taskship sync --dry-run` — it should report zero creates.")
    return "\n".join(lines)
