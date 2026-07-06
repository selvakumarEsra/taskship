"""REQ-TS-005 — idempotent sync: create / update / skip per node.

A1: first sync creates one issue per node and records key + hash in state.
A2: re-syncing an unchanged plan issues zero create and zero update calls.
A3: editing one task's title issues exactly one update of only the changed field.
A4: a story is created with its epic as parent, a task with its story as parent,
    and a child is never created before its parent.
"""
import json

from taskship import Plan
from taskship.state import StateStore
from taskship.reconcile import reconcile


PLAN = {
    "product": "Checkout Revamp", "jira_project": "CHK",
    "defaults": {"labels": ["checkout"]},
    "epics": [{"id": "guest-checkout", "title": "One-click guest checkout", "stories": [
        {"id": "guest-flow", "title": "Guest checkout flow", "tasks": [
            {"id": "biz-1", "title": "Define requirements", "type": "biz-spec"}]}]}],
}


def _state(tmp_path):
    return StateStore(tmp_path / ".taskship" / "state.json")


def test_a1_first_sync_creates_all_and_records_state(tmp_path, ):
    from tests.fakes import FakeJira
    jira, state = FakeJira(), _state(tmp_path)
    report = reconcile(Plan.from_mapping(PLAN), jira, state)

    assert len(report.created) == 3          # epic + story + task
    assert not report.updated and not report.skipped
    assert len(jira.create_calls) == 3
    # state.json persisted with a jira key + hash per node
    saved = json.loads((tmp_path / ".taskship" / "state.json").read_text())
    assert set(saved) == {"guest-checkout", "guest-checkout/guest-flow",
                          "guest-checkout/guest-flow/biz-1"}
    assert saved["guest-checkout"]["jira"] == "CHK-101"
    assert "hash" in saved["guest-checkout"]


def test_a2_resync_unchanged_is_all_skip(tmp_path):
    from tests.fakes import FakeJira
    jira, state = FakeJira(), _state(tmp_path)
    reconcile(Plan.from_mapping(PLAN), jira, state)

    jira2 = FakeJira()
    report = reconcile(Plan.from_mapping(PLAN), jira2, _state(tmp_path))  # reload state
    assert len(report.skipped) == 3
    assert not report.created and not report.updated
    assert jira2.create_calls == [] and jira2.update_calls == []


def test_a3_single_title_edit_is_one_targeted_update(tmp_path):
    from tests.fakes import FakeJira
    jira, state = FakeJira(), _state(tmp_path)
    reconcile(Plan.from_mapping(PLAN), jira, state)

    edited = json.loads(json.dumps(PLAN))
    edited["epics"][0]["stories"][0]["tasks"][0]["title"] = "Define guest requirements (v2)"
    jira2 = FakeJira()
    report = reconcile(Plan.from_mapping(edited), jira2, _state(tmp_path))

    assert len(report.updated) == 1
    assert len(report.skipped) == 2
    assert not report.created
    assert len(jira2.update_calls) == 1
    _key, changed = jira2.update_calls[0]
    assert set(changed) == {"summary"}          # only the changed field patched
    assert changed["summary"] == "Define guest requirements (v2)"


def test_a4_parent_linkage_and_ordering(tmp_path):
    from tests.fakes import FakeJira
    jira, state = FakeJira(), _state(tmp_path)
    reconcile(Plan.from_mapping(PLAN), jira, state)

    order = [ext for ext, _parent in jira.create_calls]
    epic_i = order.index("guest-checkout")
    story_i = order.index("guest-checkout/guest-flow")
    task_i = order.index("guest-checkout/guest-flow/biz-1")
    assert epic_i < story_i < task_i           # parents before children

    by_ext = {ext: parent for ext, parent in jira.create_calls}
    assert by_ext["guest-checkout"] is None                       # epic: no parent
    assert by_ext["guest-checkout/guest-flow"] == "CHK-101"        # story → epic key
    assert by_ext["guest-checkout/guest-flow/biz-1"] == "CHK-102"  # task → story key
