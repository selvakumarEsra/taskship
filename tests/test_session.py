"""REQ-TS-013 — the MCP front door drives the same engine as the CLI.

Tests target TaskShipSession (the shared engine the MCP tools wrap), so the
transport layer stays thin.

A1: sync_to_jira(dry_run=True) returns the same diff a direct reconcile() does,
    and writes nothing.
A2: add_task mutates the in-memory plan (get_plan reflects it) and serializes to
    a reviewable plan.yaml.
A3: get_board_status returns the same live view the CLI status renders.
"""
from taskship import Plan
from taskship.plan_io import load_plan
from taskship.state import StateStore
from taskship.reconcile import reconcile
from taskship.status import build_status_view
from taskship.session import TaskShipSession
from taskship.connect import OfflineClient
from tests.fakes import FakeJira

SAMPLE = (
    "product: Checkout Revamp\n"
    "jira_project: CHK\n"
    "epics:\n"
    "  - id: guest-checkout\n"
    "    title: One-click guest checkout\n"
    "    stories:\n"
    "      - id: guest-flow\n"
    "        title: Guest checkout flow\n"
    "        tasks: []\n"
)


def _session(tmp_path):
    (tmp_path / "plan.yaml").write_text(SAMPLE)
    return TaskShipSession(tmp_path)


def test_a2_add_task_mutates_plan_and_serializes(tmp_path):
    s = _session(tmp_path)
    s.add_task("guest-checkout", "guest-flow", type="biz-spec",
               title="Define requirements")

    plan = s.get_plan()
    tasks = plan["epics"][0]["stories"][0]["tasks"]
    assert any(t["title"] == "Define requirements" for t in tasks)

    s.save()
    reloaded, _raw = load_plan(tmp_path / "plan.yaml")   # reviewable + valid
    assert reloaded.epics[0].stories[0].tasks[0].title == "Define requirements"


def test_add_epic_and_story(tmp_path):
    s = _session(tmp_path)
    s.add_epic(title="Second epic", id="second")
    s.add_story("second", title="A story", id="story-2")
    s.add_task("second", "story-2", type="devops", title="Pipeline")
    plan = s.get_plan()
    assert plan["epics"][1]["id"] == "second"
    assert plan["epics"][1]["stories"][0]["tasks"][0]["title"] == "Pipeline"


def test_add_task_invalid_is_rejected(tmp_path):
    s = _session(tmp_path)
    # tech-spec/perf without metrics must be rejected (schema validator).
    import pytest
    with pytest.raises(Exception):
        s.add_task("guest-checkout", "guest-flow", type="tech-spec",
                   subtype="perf", title="No metric")
    # the plan is left unchanged after a rejected mutation
    assert s.get_plan()["epics"][0]["stories"][0]["tasks"] == []


def test_a1_sync_dry_run_matches_reconcile_and_writes_nothing(tmp_path):
    s = _session(tmp_path)
    s.add_task("guest-checkout", "guest-flow", type="biz-spec", title="Define")

    report = s.sync_to_jira(dry_run=True, client=OfflineClient())

    direct = reconcile(Plan.from_mapping(s.get_plan()), OfflineClient(),
                       StateStore(tmp_path / "throwaway.json"), dry_run=True)
    assert report["created"] == direct.created
    assert not (tmp_path / ".taskship" / "state.json").exists()


def test_a3_get_board_status_matches_cli_view(tmp_path):
    s = _session(tmp_path)
    s.add_task("guest-checkout", "guest-flow", type="biz-spec", title="Define")
    s.save()

    jira = FakeJira()
    s.sync_to_jira(client=jira)                      # real sync populates state
    jira.board = {"CHK-101": {"status": "Done", "assignee": "al", "story_points": 2}}

    tool_rows = s.get_board_status(client=jira)

    # equivalent to the CLI/status engine view
    plan, _ = load_plan(tmp_path / "plan.yaml")
    cli_rows = build_status_view(plan, jira, StateStore(tmp_path / ".taskship" / "state.json"))
    assert [r["external_id"] for r in tool_rows] == [r.external_id for r in cli_rows]
    assert tool_rows[0]["status"] == "Done"
