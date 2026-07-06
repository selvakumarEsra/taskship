"""REQ-TS-008 — removing a node flags, never deletes.

A1: a node dropped from the plan gets taskship:orphaned; no delete/close call.
A2: the orphaned node is reported in the sync summary.
"""
import json

from taskship import Plan
from taskship.state import StateStore
from taskship.reconcile import reconcile, ORPHAN_LABEL
from tests.fakes import FakeJira

FULL = {
    "product": "P", "jira_project": "CHK",
    "epics": [{"id": "e", "title": "E", "stories": [
        {"id": "s", "title": "S", "tasks": [
            {"id": "keep", "title": "Keep me", "type": "biz-spec"},
            {"id": "drop", "title": "Drop me", "type": "biz-spec"}]}]}],
}

# Same plan with the "drop" task removed.
REDUCED = json.loads(json.dumps(FULL))
REDUCED["epics"][0]["stories"][0]["tasks"] = [
    REDUCED["epics"][0]["stories"][0]["tasks"][0]
]


def test_a1_removed_node_is_flagged_not_deleted(tmp_path):
    state_path = tmp_path / "s.json"
    jira = FakeJira()
    reconcile(Plan.from_mapping(FULL), jira, StateStore(state_path))
    drop_key = json.loads(state_path.read_text())["e/s/drop"]["jira"]

    jira2 = FakeJira()
    reconcile(Plan.from_mapping(REDUCED), jira2, StateStore(state_path))

    # the orphaned issue got the orphaned label...
    assert (drop_key, ORPHAN_LABEL) in jira2.label_calls
    # ...and TaskShip has no way to delete: the client exposes no delete method
    assert not hasattr(jira2, "delete") or (drop_key, "delete") not in getattr(jira2, "update_calls", [])
    # no delete/transition happened — only a label add
    assert jira2.update_calls == [] or all(
        "status" not in fields for _k, fields in jira2.update_calls
    )


def test_a2_orphan_reported_in_summary(tmp_path):
    state_path = tmp_path / "s.json"
    reconcile(Plan.from_mapping(FULL), FakeJira(), StateStore(state_path))
    report = reconcile(Plan.from_mapping(REDUCED), FakeJira(), StateStore(state_path))

    assert report.orphaned == ["e/s/drop"]
    orphan_decisions = [d for d in report.decisions if d.action == "orphan"]
    assert len(orphan_decisions) == 1
    assert orphan_decisions[0].external_id == "e/s/drop"


def test_orphan_dropped_from_state_not_reflagged(tmp_path):
    state_path = tmp_path / "s.json"
    reconcile(Plan.from_mapping(FULL), FakeJira(), StateStore(state_path))
    reconcile(Plan.from_mapping(REDUCED), FakeJira(), StateStore(state_path))

    # a second reduced sync must not re-flag the already-handled orphan
    jira3 = FakeJira()
    report = reconcile(Plan.from_mapping(REDUCED), jira3, StateStore(state_path))
    assert report.orphaned == []
    assert jira3.label_calls == []


def test_dry_run_orphan_is_reported_but_not_flagged(tmp_path):
    state_path = tmp_path / "s.json"
    reconcile(Plan.from_mapping(FULL), FakeJira(), StateStore(state_path))
    jira = FakeJira()
    report = reconcile(Plan.from_mapping(REDUCED), jira, StateStore(state_path), dry_run=True)
    assert report.orphaned == ["e/s/drop"]
    assert jira.label_calls == []  # dry-run flags nothing
