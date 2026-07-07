"""REQ-DEL-002 — cascading sprint synced to the Jira sprint field.

A1: sprint cascades and overrides like assignee.
A2: a changed resolved sprint → one update; unchanged → skip.
A3: a node with no sprint anywhere leaves the sprint field unwritten.
"""
import json

import httpx

from taskship import Plan
from taskship.cascade import resolve_plan
from taskship.payload import build_payloads
from taskship.state import StateStore
from taskship.reconcile import reconcile
from taskship.jira import JiraClient
from tests.fakes import FakeJira

PLAN = {
    "product": "P", "jira_project": "CHK",
    "epics": [{"id": "e", "title": "E", "stories": [
        {"id": "s", "title": "S", "sprint": "Sprint 12", "tasks": [
            {"id": "t1", "title": "T1", "type": "biz-spec"},
            {"id": "t2", "title": "T2", "type": "biz-spec", "sprint": "Sprint 13"}]}]}],
}


def test_a1_sprint_cascades_with_override():
    resolved = resolve_plan(Plan.from_mapping(PLAN))
    assert resolved["e/s"].sprint == "Sprint 12"
    assert resolved["e/s/t1"].sprint == "Sprint 12"      # inherits story
    assert resolved["e/s/t2"].sprint == "Sprint 13"      # overrides


def test_a2_sprint_change_is_one_update_then_skip(tmp_path):
    state_path = tmp_path / "s.json"
    reconcile(Plan.from_mapping(PLAN), FakeJira(), StateStore(state_path))
    assert reconcile(Plan.from_mapping(PLAN), FakeJira(), StateStore(state_path)).updated == []

    edited = json.loads(json.dumps(PLAN))
    edited["epics"][0]["stories"][0]["tasks"][0]["sprint"] = "Sprint 14"
    jira = FakeJira()
    r = reconcile(Plan.from_mapping(edited), jira, StateStore(state_path))
    assert r.updated == ["e/s/t1"]
    _key, changed = jira.update_calls[0]
    assert changed.get("sprint") == "Sprint 14"


def test_a3_no_sprint_is_not_written():
    plan = {"product": "P", "jira_project": "CHK",
            "epics": [{"id": "e", "title": "E", "stories": [
                {"id": "s", "title": "S", "tasks": [
                    {"id": "t", "title": "T", "type": "biz-spec"}]}]}]}
    payloads = {p.external_id: p for p in build_payloads(Plan.from_mapping(plan))}
    assert "sprint" not in payloads["e/s/t"].fields
    assert "assignee" not in payloads["e/s/t"].fields


def test_real_client_writes_sprint_to_configured_field():
    captured = {}

    def handler(request):
        if request.method == "POST" and request.url.path == "/rest/api/3/issue":
            captured["fields"] = json.loads(request.content)["fields"]
            return httpx.Response(201, json={"key": "CHK-1"})
        return httpx.Response(200, json={})

    http = httpx.Client(transport=httpx.MockTransport(handler),
                        base_url="https://x.atlassian.net", auth=("e", "t"))
    client = JiraClient("https://x.atlassian.net", "e", "t", "CHK",
                        sprint_field="customfield_10020", client=http)
    payload = build_payloads(Plan.from_mapping(PLAN))
    story = next(p for p in payload if p.external_id == "e/s")
    client.create(story, None)
    assert captured["fields"].get("customfield_10020") == "Sprint 12"
