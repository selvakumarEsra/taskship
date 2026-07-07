"""REQ-DEL-001 — cascading assignee synced to Jira idempotently.

A1: assignee cascades defaults→epic→story→task, narrower scope overrides.
A2: a changed resolved assignee → exactly one update; unchanged → skip.
A3: an unresolvable assignee errors for that node without aborting the others.
A4: `taskship assign <node-id> <assignee>` sets it in plan.yaml.
"""
import json

import pytest
from click.testing import CliRunner

from taskship import Plan
from taskship.cascade import resolve_plan
from taskship.state import StateStore
from taskship.reconcile import reconcile
from taskship.cli import cli
from tests.fakes import FakeJira

PLAN = {
    "product": "P", "jira_project": "CHK",
    "defaults": {"assignee": "lead@acme.com"},
    "epics": [{"id": "e", "title": "E", "stories": [
        {"id": "s", "title": "S", "assignee": "alice@acme.com", "tasks": [
            {"id": "t1", "title": "T1", "type": "biz-spec"},
            {"id": "t2", "title": "T2", "type": "biz-spec", "assignee": "bob@acme.com"}]}]}],
}


def test_a1_assignee_cascades_with_override():
    resolved = resolve_plan(Plan.from_mapping(PLAN))
    assert resolved["e"].assignee == "lead@acme.com"           # from defaults
    assert resolved["e/s"].assignee == "alice@acme.com"        # story overrides
    assert resolved["e/s/t1"].assignee == "alice@acme.com"     # inherits story
    assert resolved["e/s/t2"].assignee == "bob@acme.com"       # task overrides


def test_a2_assignee_change_is_one_update_then_skip(tmp_path):
    state_path = tmp_path / "s.json"
    reconcile(Plan.from_mapping(PLAN), FakeJira(), StateStore(state_path))

    # Re-sync unchanged → all skip.
    r2 = reconcile(Plan.from_mapping(PLAN), FakeJira(), StateStore(state_path))
    assert r2.updated == []

    # Change t1's assignee → exactly one update carrying the assignee field.
    edited = json.loads(json.dumps(PLAN))
    edited["epics"][0]["stories"][0]["tasks"][0]["assignee"] = "carol@acme.com"
    jira = FakeJira()
    r3 = reconcile(Plan.from_mapping(edited), jira, StateStore(state_path))
    assert r3.updated == ["e/s/t1"]
    assert len(jira.update_calls) == 1
    _key, changed = jira.update_calls[0]
    assert changed.get("assignee") == "carol@acme.com"


def test_a3_unresolvable_assignee_errors_node_without_aborting_others(tmp_path):
    class PickyJira(FakeJira):
        def create(self, payload, parent_key):
            if payload.fields.get("assignee") == "ghost@acme.com":
                raise ValueError(f"no such Jira user: {payload.fields['assignee']}")
            return super().create(payload, parent_key)

    plan = {
        "product": "P", "jira_project": "CHK",
        "epics": [{"id": "e", "title": "E", "stories": [
            {"id": "s", "title": "S", "tasks": [
                {"id": "ok", "title": "Ok", "type": "biz-spec", "assignee": "real@acme.com"},
                {"id": "bad", "title": "Bad", "type": "biz-spec", "assignee": "ghost@acme.com"}]}]}],
    }
    jira = PickyJira()
    report = reconcile(Plan.from_mapping(plan), jira, StateStore(tmp_path / "s.json"))

    # the good nodes still got created
    assert "e/s/ok" in report.created
    # the bad node is reported as an error naming it, not a crash
    assert any(err.external_id == "e/s/bad" for err in report.errors)
    assert any("ghost@acme.com" in err.message for err in report.errors)


def test_a4_assign_command_sets_plan_yaml(tmp_path):
    (tmp_path / "plan.yaml").write_text(
        "product: P\njira_project: CHK\nepics:\n"
        "  - id: e\n    title: E\n    stories:\n"
        "      - id: s\n        title: S\n        tasks:\n"
        "          - id: t\n            title: T\n            type: biz-spec\n"
    )
    result = CliRunner().invoke(cli, ["--dir", str(tmp_path), "assign", "e/s/t", "dana@acme.com"])
    assert result.exit_code == 0, result.output

    from taskship.plan_io import load_plan
    plan, _ = load_plan(tmp_path / "plan.yaml")
    assert plan.epics[0].stories[0].tasks[0].assignee == "dana@acme.com"
