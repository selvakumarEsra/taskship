"""REQ-TS-003 — fields cascade defaults → epic → story → task.

A1: a task with no labels inherits its story's, which fall back to defaults.
A2: a task with its own labels overrides (not unions), unless it opts into merge.
A3: the resolved (post-cascade) field set for any node is inspectable.
"""
from taskship import Plan
from taskship.cascade import effective_labels, resolve_plan
from taskship.identity import qualified_id


def _plan(**epics_kw):
    return Plan.from_mapping(epics_kw)


def test_a1_task_inherits_story_then_defaults():
    plan = Plan.from_mapping({
        "product": "P", "jira_project": "CHK",
        "defaults": {"labels": ["checkout", "fy26-q3"]},
        "epics": [{"id": "e", "title": "E", "stories": [
            # story overrides labels; its task inherits the story's
            {"id": "s1", "title": "S1", "labels": ["frontend"], "tasks": [
                {"id": "t1", "title": "T1", "type": "biz-spec"}]},
            # story with no labels; its task falls back to defaults
            {"id": "s2", "title": "S2", "tasks": [
                {"id": "t2", "title": "T2", "type": "biz-spec"}]},
        ]}],
    })
    resolved = resolve_plan(plan)
    assert resolved["e/s1"].labels == ["frontend"]
    assert resolved["e/s1/t1"].labels == ["frontend"]          # inherits story
    assert resolved["e/s2/t2"].labels == ["checkout", "fy26-q3"]  # falls back to defaults


def test_a2_task_labels_override_not_union():
    plan = Plan.from_mapping({
        "product": "P", "jira_project": "CHK",
        "defaults": {"labels": ["checkout"]},
        "epics": [{"id": "e", "title": "E", "stories": [
            {"id": "s", "title": "S", "labels": ["frontend"], "tasks": [
                {"id": "t", "title": "T", "type": "biz-spec", "labels": ["security"]}]}]}],
    })
    resolved = resolve_plan(plan)
    # exactly its own labels — no inherited "checkout"/"frontend" merged in
    assert resolved["e/s/t"].labels == ["security"]


def test_a2_explicit_merge_unions_with_inherited():
    plan = Plan.from_mapping({
        "product": "P", "jira_project": "CHK",
        "defaults": {"labels": ["checkout"]},
        "epics": [{"id": "e", "title": "E", "stories": [
            {"id": "s", "title": "S", "labels": ["frontend"], "tasks": [
                {"id": "t", "title": "T", "type": "biz-spec",
                 "labels": ["security"], "labels_merge": True}]}]}],
    })
    resolved = resolve_plan(plan)
    # opt-in merge unions inherited (frontend) with own (security), order preserved, deduped
    assert resolved["e/s/t"].labels == ["frontend", "security"]


def test_effective_labels_override_and_merge_unit():
    assert effective_labels(["a", "b"], node_labels=None, merge=False) == ["a", "b"]
    assert effective_labels(["a", "b"], node_labels=["c"], merge=False) == ["c"]
    assert effective_labels(["a", "b"], node_labels=["b", "c"], merge=True) == ["a", "b", "c"]


def test_a3_resolved_fields_inspectable_for_every_node():
    plan = Plan.from_mapping({
        "product": "P", "jira_project": "CHK",
        "defaults": {"labels": ["checkout"]},
        "epics": [{"id": "e", "title": "E", "stories": [
            {"id": "s", "title": "S", "tasks": [
                {"id": "t", "title": "T", "type": "biz-spec"}]}]}],
    })
    resolved = resolve_plan(plan)
    # every node in the plan has an inspectable resolved entry
    assert set(resolved) == {"e", "e/s", "e/s/t"}
    assert resolved[qualified_id("e", "s", "t")].labels == ["checkout"]
