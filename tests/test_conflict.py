"""REQ-TS-011 — divergence between plan and board is surfaced, not overwritten.

A1: a hand edit to a managed field + a plan change to that field is reported as
    a conflict listing the field, the plan value, and the board value.
A2: the conflicting field is not overwritten by that sync.
"""
import json

from taskship import Plan
from taskship.state import StateStore
from taskship.reconcile import reconcile
from tests.fakes import FakeJira

PLAN = {
    "product": "P", "jira_project": "CHK",
    "epics": [{"id": "e", "title": "Epic", "stories": [
        {"id": "s", "title": "Story", "tasks": [
            {"id": "t", "title": "Original title", "type": "biz-spec"}]}]}],
}


def _edit_task_title(plan_dict, new_title):
    d = json.loads(json.dumps(plan_dict))
    d["epics"][0]["stories"][0]["tasks"][0]["title"] = new_title
    return d


def test_a1_and_a2_hand_edit_plus_plan_change_is_conflict(tmp_path):
    state_path = tmp_path / "s.json"
    jira = FakeJira()
    reconcile(Plan.from_mapping(PLAN), jira, StateStore(state_path))
    task_key = json.loads(state_path.read_text())["e/s/t"]["jira"]

    # Someone hand-edits the task summary on the board...
    jira2 = FakeJira()
    jira2.current = {task_key: {"summary": "HAND EDITED ON BOARD"}}
    # ...and the plan also changes that task's title.
    edited = _edit_task_title(PLAN, "PLAN WANTS THIS")

    report = reconcile(Plan.from_mapping(edited), jira2, StateStore(state_path))

    # A1: reported as a conflict with field + both values
    assert len(report.conflicts) == 1
    c = report.conflicts[0]
    assert c.external_id == "e/s/t"
    assert c.field == "summary"
    assert c.plan_value == "PLAN WANTS THIS"
    assert c.board_value == "HAND EDITED ON BOARD"

    # A2: the conflicting field was NOT overwritten
    summary_patches = [
        fields for _k, fields in jira2.update_calls if "summary" in fields
    ]
    assert summary_patches == []


def test_no_conflict_when_board_untouched(tmp_path):
    # Board still matches what TaskShip last wrote → a plan change just updates.
    state_path = tmp_path / "s.json"
    jira = FakeJira()
    reconcile(Plan.from_mapping(PLAN), jira, StateStore(state_path))

    jira2 = FakeJira()
    jira2.current = {json.loads(state_path.read_text())["e/s/t"]["jira"]:
                     {"summary": "Original title"}}  # unchanged on board
    edited = _edit_task_title(PLAN, "New planned title")
    report = reconcile(Plan.from_mapping(edited), jira2, StateStore(state_path))

    assert report.conflicts == []
    # the plan change is applied normally
    assert any("summary" in fields for _k, fields in jira2.update_calls)


def test_conflict_resurfaces_until_resolved(tmp_path):
    state_path = tmp_path / "s.json"
    reconcile(Plan.from_mapping(PLAN), FakeJira(), StateStore(state_path))
    task_key = json.loads(state_path.read_text())["e/s/t"]["jira"]
    edited = _edit_task_title(PLAN, "PLAN WANTS THIS")

    def sync_once():
        j = FakeJira()
        j.current = {task_key: {"summary": "HAND EDITED ON BOARD"}}
        return reconcile(Plan.from_mapping(edited), j, StateStore(state_path))

    assert len(sync_once().conflicts) == 1
    # unresolved conflict is not silently swallowed; it surfaces again
    assert len(sync_once().conflicts) == 1
