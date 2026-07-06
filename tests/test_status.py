"""REQ-TS-010 — reverse sync pulls live board state without overwriting intent.

A1: status fetches each mapped issue's status/assignee/story points, shown per node.
A2: reverse sync leaves plan.yaml's authored fields unchanged on disk.
"""
from taskship import Plan
from taskship.plan_io import load_plan, dump_plan
from taskship.state import StateStore
from taskship.reconcile import reconcile
from taskship.status import build_status_view
from tests.fakes import FakeJira

PLAN = {
    "product": "P", "jira_project": "CHK",
    "epics": [{"id": "e", "title": "Epic", "stories": [
        {"id": "s", "title": "Story", "tasks": [
            {"id": "t", "title": "Task", "type": "biz-spec"}]}]}],
}


def test_a1_status_view_pairs_plan_nodes_with_live_state(tmp_path):
    state = StateStore(tmp_path / "s.json")
    jira = FakeJira()
    reconcile(Plan.from_mapping(PLAN), jira, state)

    # Seed live board state for the created issues.
    jira.board = {
        "CHK-101": {"status": "In Progress", "assignee": "alice", "story_points": 5},
        "CHK-102": {"status": "To Do", "assignee": None, "story_points": None},
        "CHK-103": {"status": "Done", "assignee": "bob", "story_points": 3},
    }

    view = build_status_view(Plan.from_mapping(PLAN), jira, state)
    by_id = {row.external_id: row for row in view}

    assert by_id["e"].jira == "CHK-101"
    assert by_id["e"].status == "In Progress"
    assert by_id["e"].assignee == "alice"
    assert by_id["e"].story_points == 5
    assert by_id["e/s/t"].status == "Done"
    assert by_id["e/s/t"].title == "Task"          # planned title carried through


def test_a1_unsynced_node_shows_no_live_state(tmp_path):
    # A node not yet in state has no Jira key and reports no live status.
    state = StateStore(tmp_path / "s.json")   # empty
    jira = FakeJira()
    view = build_status_view(Plan.from_mapping(PLAN), jira, state)
    assert all(row.jira is None and row.status is None for row in view)


def test_a2_reverse_sync_does_not_modify_plan_file(tmp_path):
    plan_path = tmp_path / "plan.yaml"
    src = (
        "product: P   # authored comment\n"
        "jira_project: CHK\n"
        "epics:\n"
        "  - id: e\n"
        "    title: Epic\n"
        "    stories:\n"
        "      - id: s\n"
        "        title: Story\n"
        "        tasks:\n"
        "          - id: t\n"
        "            title: Task\n"
        "            type: biz-spec\n"
    )
    plan_path.write_text(src)
    plan, _raw = load_plan(plan_path)

    state = StateStore(tmp_path / "s.json")
    jira = FakeJira()
    reconcile(plan, jira, state)
    jira.board = {"CHK-101": {"status": "Done", "assignee": "x", "story_points": 1}}

    build_status_view(plan, jira, state)   # read-only reverse sync

    assert plan_path.read_text() == src    # authored file untouched byte-for-byte
