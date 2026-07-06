"""REQ-TS-007 — sync --dry-run performs no writes.

A1: dry-run reports create/update/skip per node with a reason, zero mutations.
A2: dry-run leaves .taskship/state.json byte-for-byte unchanged.
"""
from taskship import Plan
from taskship.state import StateStore
from taskship.reconcile import reconcile
from tests.fakes import FakeJira

PLAN = {
    "product": "P", "jira_project": "CHK",
    "epics": [{"id": "e", "title": "E", "stories": [
        {"id": "s", "title": "S", "tasks": [
            {"id": "b", "title": "T", "type": "biz-spec"}]}]}],
}


def test_a1_dry_run_reports_plan_and_makes_no_mutations(tmp_path):
    jira = FakeJira()
    report = reconcile(Plan.from_mapping(PLAN), jira,
                       StateStore(tmp_path / "s.json"), dry_run=True)

    # one decision per node, each a valid action with a reason
    assert len(report.decisions) == 3
    assert {d.action for d in report.decisions} == {"create"}
    assert all(d.reason for d in report.decisions)
    assert report.created == ["e", "e/s", "e/s/b"]
    # zero mutating calls
    assert jira.create_calls == []
    assert jira.update_calls == []
    assert jira.label_calls == []


def test_a2_dry_run_leaves_state_file_unchanged(tmp_path):
    state_path = tmp_path / ".taskship" / "state.json"

    # No state file yet: a dry-run must not create one.
    reconcile(Plan.from_mapping(PLAN), FakeJira(), StateStore(state_path), dry_run=True)
    assert not state_path.exists()

    # Existing state file: a dry-run must not modify its bytes.
    jira = FakeJira()
    reconcile(Plan.from_mapping(PLAN), jira, StateStore(state_path))  # real sync writes state
    before = state_path.read_bytes()
    reconcile(Plan.from_mapping(PLAN), FakeJira(), StateStore(state_path), dry_run=True)
    assert state_path.read_bytes() == before


def test_dry_run_then_real_sync_is_consistent(tmp_path):
    # A dry-run's plan matches what the real sync actually does.
    dry = reconcile(Plan.from_mapping(PLAN), FakeJira(),
                    StateStore(tmp_path / "s.json"), dry_run=True)
    real = reconcile(Plan.from_mapping(PLAN), FakeJira(),
                     StateStore(tmp_path / "s.json"))
    assert dry.created == real.created
