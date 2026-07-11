"""REQ-DEL-003/004/005 — board, standup, exec report (all read-only)."""
import json

from click.testing import CliRunner

from taskship import Plan
from taskship.plan_io import load_plan
from taskship.state import StateStore
from taskship.reconcile import reconcile
from taskship.status import build_status_view
from taskship.ceremonies import (
    board_columns, is_done, is_blocked, standup_snapshot, standup_diff,
    render_standup_md, build_report, render_report_html, triage_observations,
)
from taskship.payload import build_payloads
from taskship.cli import cli
from tests.fakes import FakeJira

PLAN = {
    "product": "Checkout", "jira_project": "CHK",
    "epics": [{"id": "e", "title": "Checkout epic", "stories": [
        {"id": "s", "title": "Flow", "tasks": [
            {"id": "t1", "title": "Task one", "type": "biz-spec", "assignee": "alice"},
            {"id": "t2", "title": "Task two", "type": "biz-spec", "assignee": "bob"},
            {"id": "t3", "title": "Task three", "type": "biz-spec", "assignee": "alice"}]}]}],
}

PLAN_YAML = (
    "product: Checkout\njira_project: CHK\nepics:\n"
    "  - id: e\n    title: Checkout epic\n    stories:\n"
    "      - id: s\n        title: Flow\n        tasks:\n"
    "          - id: t1\n            title: Task one\n            type: biz-spec\n            assignee: alice\n"
    "          - id: t2\n            title: Task two\n            type: biz-spec\n            assignee: bob\n"
    "          - id: t3\n            title: Task three\n            type: biz-spec\n            assignee: alice\n"
)


def _synced(tmp_path):
    """Sync PLAN with a FakeJira and return (jira, state_path) with board data."""
    state_path = tmp_path / ".taskship" / "state.json"
    jira = FakeJira()
    reconcile(Plan.from_mapping(PLAN), jira, StateStore(state_path))
    saved = json.loads(state_path.read_text())
    jira.board = {
        saved["e/s/t1"]["jira"]: {"status": "Done", "assignee": "alice", "story_points": 3},
        saved["e/s/t2"]["jira"]: {"status": "In Progress", "assignee": "bob", "story_points": 2},
        saved["e/s/t3"]["jira"]: {"status": "Blocked", "assignee": "alice", "story_points": 1},
    }
    return jira, state_path


def _rows(tmp_path):
    jira, state_path = _synced(tmp_path)
    return build_status_view(Plan.from_mapping(PLAN), jira, StateStore(state_path))


# --- helpers ---------------------------------------------------------------

def test_done_and_blocked_helpers():
    assert is_done("Done") and is_done("closed") and not is_done("In Progress")
    assert is_blocked("Blocked") and not is_blocked("In Progress")


# --- REQ-DEL-003 board ------------------------------------------------------

def test_a3_board_groups_tasks_by_status(tmp_path):
    cols = board_columns(_rows(tmp_path))
    assert [r.title for r in cols["Done"]] == ["Task one"]
    assert [r.title for r in cols["In Progress"]] == ["Task two"]
    assert "Blocked" in cols and cols["Blocked"][0].title == "Task three"


def test_board_backlog_holds_unsynced(tmp_path):
    # No sync at all → every task lands in Backlog with no status.
    rows = build_status_view(Plan.from_mapping(PLAN), FakeJira(),
                             StateStore(tmp_path / "empty.json"))
    cols = board_columns(rows)
    assert len(cols["Backlog"]) == 3


def test_board_cli_read_only(tmp_path, monkeypatch):
    (tmp_path / "plan.yaml").write_text(PLAN_YAML)
    jira, _ = _synced(tmp_path)
    monkeypatch.setattr("taskship.cli._build_client", lambda cfg: jira)
    before = (tmp_path / "plan.yaml").read_bytes()
    result = CliRunner().invoke(cli, ["--dir", str(tmp_path), "board"])
    assert result.exit_code == 0, result.output
    assert "IN PROGRESS" in result.output and "Task two" in result.output
    assert (tmp_path / "plan.yaml").read_bytes() == before  # read-only


# --- REQ-DOORS-003 triage lane ----------------------------------------------

_INTAKE_PLAN = {
    "product": "Checkout", "jira_project": "CHK",
    "epics": [
        {"id": "e", "title": "Product", "stories": [
            {"id": "s", "title": "Flow", "tasks": [
                {"id": "t1", "title": "Work item", "type": "biz-spec"}]}]},
        {"id": "ops-intake", "title": "Ops intake", "stories": [
            {"id": "observations", "title": "Observations", "kind": "ops", "tasks": [
                {"id": "obs-1", "title": "500s on checkout", "type": "ops-observation",
                 "fields": {"observation": "5xx", "impact": "guests"}}]}]},
    ],
}


def test_doors003_a1_triage_group_separates_observations():
    rows = build_status_view(Plan.from_mapping(_INTAKE_PLAN), FakeJira(),
                             StateStore("/nonexistent.json"))
    triage = triage_observations(rows)
    assert [r.title for r in triage] == ["500s on checkout"]
    # the observation is NOT double-counted in the status columns.
    cols = board_columns(rows)
    all_titles = [r.title for items in cols.values() for r in items]
    assert "500s on checkout" not in all_titles
    assert "Work item" in all_titles


def test_doors003_a3_empty_intake_renders_clean():
    plan = {"product": "P", "jira_project": "PR", "epics": [
        {"id": "e", "title": "E", "stories": [
            {"id": "s", "title": "S", "tasks": [
                {"id": "t", "title": "T", "type": "biz-spec"}]}]}]}
    rows = build_status_view(Plan.from_mapping(plan), FakeJira(),
                             StateStore("/nonexistent.json"))
    assert triage_observations(rows) == []  # empty, not an error


def test_doors003_a1_board_cli_shows_triage(tmp_path, monkeypatch):
    yaml = (
        "product: Checkout\njira_project: CHK\nepics:\n"
        "  - id: e\n    title: Product\n    stories:\n"
        "      - id: s\n        title: Flow\n        tasks:\n"
        "          - id: t1\n            title: Work item\n            type: biz-spec\n"
        "  - id: ops-intake\n    title: Ops intake\n    stories:\n"
        "      - id: observations\n        title: Observations\n        kind: ops\n        tasks:\n"
        "          - id: obs-1\n            title: 500s on checkout\n            type: ops-observation\n"
        "            fields: {observation: 5xx, impact: guests}\n"
    )
    (tmp_path / "plan.yaml").write_text(yaml)
    monkeypatch.setattr("taskship.cli._build_client", lambda cfg: FakeJira())
    result = CliRunner().invoke(cli, ["--dir", str(tmp_path), "board"])
    assert result.exit_code == 0, result.output
    assert "TRIAGE" in result.output and "500s on checkout" in result.output


# --- REQ-DOORS-003 A2: sync never writes Jira priority ----------------------

def test_doors003_a2_sync_payloads_never_carry_priority():
    plan = Plan.from_mapping(_INTAKE_PLAN)
    for payload in build_payloads(plan):
        assert "priority" not in payload.fields
        assert "priority" not in payload.field_hashes
        assert all("priority" not in label.lower() for label in payload.labels)


# --- REQ-DEL-004 standup ----------------------------------------------------

def test_a4_standup_diff_classifies_and_groups(tmp_path):
    rows = _rows(tmp_path)
    prev = {"e/s/t1": "In Progress"}  # t1 was in progress, now Done
    diff = standup_diff(prev, rows, conflict_ids={"e/s/t2"})
    alice = {i.external_id: i for i in diff["alice"]}
    assert alice["e/s/t1"].state == "done_since"        # transitioned to done
    assert alice["e/s/t3"].blocked is True              # Blocked status flagged
    bob = {i.external_id: i for i in diff["bob"]}
    assert bob["e/s/t2"].conflict is True               # conflict flagged
    md = render_standup_md(diff)
    assert "## alice" in md and "## bob" in md


def test_standup_snapshot_roundtrip(tmp_path):
    snap = standup_snapshot(_rows(tmp_path))
    assert snap["e/s/t1"] == "Done" and snap["e/s/t2"] == "In Progress"


def test_a4_standup_cli_writes_markdown_and_snapshot(tmp_path, monkeypatch):
    (tmp_path / "plan.yaml").write_text(PLAN_YAML)
    jira, _ = _synced(tmp_path)
    monkeypatch.setattr("taskship.cli._build_client", lambda cfg: jira)
    before = (tmp_path / "plan.yaml").read_bytes()
    result = CliRunner().invoke(cli, ["--dir", str(tmp_path), "standup"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "standup.md").exists()
    assert (tmp_path / ".taskship" / "standup.json").exists()
    assert (tmp_path / "plan.yaml").read_bytes() == before  # read-only


# --- REQ-DEL-005 report -----------------------------------------------------

def test_a5_report_rollup(tmp_path):
    data = build_report(_rows(tmp_path))
    epic = data.epics[0]
    assert epic.total == 3 and epic.done == 1 and epic.pct == 33
    assert data.workload["alice"]["total"] == 2 and data.workload["alice"]["done"] == 1
    assert len(data.blocked) == 1  # Task three


def test_a5_report_html_self_contained(tmp_path):
    data = build_report(_rows(tmp_path), conflicts=[{"id": "e/s/t2", "field": "summary"}],
                        orphans=["e/s/gone"])
    doc = render_report_html(data, "Checkout")
    assert doc.strip().startswith("<!doctype html>")
    assert "<style>" in doc            # styles inlined, self-contained
    assert "http://" not in doc and "https://" not in doc  # no external fetch
    assert "Checkout" in doc and "alice" in doc and "33%" in doc
    assert "Conflict" in doc and "Orphaned" in doc


def test_a5_report_cli_writes_html_read_only(tmp_path, monkeypatch):
    (tmp_path / "plan.yaml").write_text(PLAN_YAML)
    jira, _ = _synced(tmp_path)
    monkeypatch.setattr("taskship.cli._build_client", lambda cfg: jira)
    before = (tmp_path / "plan.yaml").read_bytes()
    result = CliRunner().invoke(cli, ["--dir", str(tmp_path), "report"])
    assert result.exit_code == 0, result.output
    out = tmp_path / "status-report.html"
    assert out.exists() and "<!doctype html>" in out.read_text()
    assert (tmp_path / "plan.yaml").read_bytes() == before
