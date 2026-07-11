"""ONBOARD-DOC — import an existing Jira project into plan-as-code.

REQ-ONBOARD-001: build a schema-valid draft plan mirroring the Jira hierarchy.
REQ-ONBOARD-002: adopt existing issue keys so the first sync never duplicates.
REQ-ONBOARD-003: imported tasks keep their Jira descriptions untouched by sync.
REQ-ONBOARD-004: guarded one-time bootstrap; atomic (all-or-nothing) writes.
REQ-ONBOARD-005: print a review summary (counts, tree, noise flags, next steps).
"""
import httpx
import pytest
from click.testing import CliRunner
from ruamel.yaml.comments import CommentedMap

from taskship.cli import cli
from taskship.onboard import (
    CATCH_ALL_EPIC_ID,
    ORPHAN_STORY_ID,
    OnboardError,
    OnboardResult,
    build_payloads,
    format_onboard_summary,
    infer_task_type,
    onboard_project,
)
from taskship.plan_io import load_plan
from taskship.reconcile import reconcile
from taskship.state import StateStore


# --- fakes / fixtures ------------------------------------------------------

def raw(key, itype, summary="S", parent=None, labels=None,
        status="To Do", category="new"):
    """A raw Jira issue as /rest/api/3/search/jql returns it."""
    fields = {
        "summary": summary,
        "issuetype": {"name": itype},
        "labels": list(labels or []),
        "status": {"name": status, "statusCategory": {"key": category}},
    }
    if parent:
        fields["parent"] = {"key": parent}
    return {"key": key, "fields": fields}


class FakeOnboardJira:
    """Serves canned issues to onboard; also usable as a reconcile client."""

    def __init__(self, issues, project_key="PROJ"):
        self._issues = issues
        self.project_key = project_key

    def search_project_issues(self):
        return list(self._issues)

    # reconcile-side surface (unused when state already has every key):
    def search_by_external_id(self, external_id):
        return None


class BoomJira:
    """Fails mid-import to exercise atomicity (REQ-ONBOARD-004.A2)."""

    project_key = "PROJ"

    def search_project_issues(self):
        raise RuntimeError("network down mid-import")


CLEAN = [
    raw("PROJ-1", "Epic", "Checkout revamp"),
    raw("PROJ-2", "Story", "Guest flow", parent="PROJ-1"),
    raw("PROJ-3", "Task", "Define requirements", parent="PROJ-2"),
    raw("PROJ-4", "Task", "Legacy biz spec", parent="PROJ-2",
        labels=["taskship:type:biz-spec", "keepme"]),
]


# --- REQ-ONBOARD-001 -------------------------------------------------------

def test_a1_builds_plan_mirroring_hierarchy(tmp_path):
    onboard_project(FakeOnboardJira(CLEAN), "PROJ", tmp_path)
    plan, _raw = load_plan(tmp_path / "plan.yaml")

    assert plan.jira_project == "PROJ"
    assert [e.title for e in plan.epics] == ["Checkout revamp"]
    epic = plan.epics[0]
    assert [s.title for s in epic.stories] == ["Guest flow"]
    assert [t.title for t in epic.stories[0].tasks] == \
        ["Define requirements", "Legacy biz spec"]


def test_a2_ids_are_pinned_and_derived_from_jira_keys(tmp_path):
    onboard_project(FakeOnboardJira(CLEAN), "PROJ", tmp_path)
    plan, _raw = load_plan(tmp_path / "plan.yaml")

    assert plan.epics[0].id == "proj-1"
    assert plan.epics[0].stories[0].id == "proj-2"
    assert plan.epics[0].stories[0].tasks[0].id == "proj-3"


def test_a3_orphans_land_in_catch_all_epic(tmp_path):
    issues = [
        raw("PROJ-1", "Epic", "Real epic"),
        raw("PROJ-2", "Story", "Homeless story"),          # no parent epic
        raw("PROJ-3", "Task", "Homeless task"),            # no parent story
        raw("PROJ-4", "Task", "Task under epic", parent="PROJ-1"),  # parent is epic
    ]
    onboard_project(FakeOnboardJira(issues), "PROJ", tmp_path)
    plan, _raw = load_plan(tmp_path / "plan.yaml")

    catch_all = next(e for e in plan.epics if e.id == CATCH_ALL_EPIC_ID)
    story_ids = {s.id for s in catch_all.stories}
    assert "proj-2" in story_ids                            # homeless story adopted
    orphan_story = next(s for s in catch_all.stories if s.id == ORPHAN_STORY_ID)
    orphan_task_ids = {t.id for t in orphan_story.tasks}
    assert {"proj-3", "proj-4"} <= orphan_task_ids          # both tasks kept, not dropped


def test_a3_unrecognized_types_are_skipped_with_counts(tmp_path):
    issues = CLEAN + [
        raw("PROJ-9", "Bug", "A bug"),
        raw("PROJ-10", "Sub-task", "A sub-task"),
    ]
    result = onboard_project(FakeOnboardJira(issues), "PROJ", tmp_path)
    reasons = result.skipped_by_reason
    assert reasons.get("unrecognized issue type: Bug") == 1
    assert reasons.get("unrecognized issue type: Sub-task") == 1
    # skipped issues never make it into the plan
    plan, _raw = load_plan(tmp_path / "plan.yaml")
    all_ids = {e.id for e in plan.epics}
    for e in plan.epics:
        for s in e.stories:
            all_ids |= {s.id} | {t.id for t in s.tasks}
    assert "proj-9" not in all_ids and "proj-10" not in all_ids


def test_a4_invalid_plan_is_named_error_and_writes_nothing(tmp_path, monkeypatch):
    bad = CommentedMap()
    bad["product"] = "P"
    bad["jira_project"] = "PROJ"
    bad["epics"] = []
    bad["bogus_extra"] = 1  # extra="forbid" → PlanValidationError
    stub_result = OnboardResult(project_key="PROJ", plan=None,
                                counts={"epics": 0, "stories": 0, "tasks": 0})
    monkeypatch.setattr("taskship.onboard.build_plan",
                        lambda *a, **k: (bad, {}, stub_result))
    with pytest.raises(OnboardError):
        onboard_project(FakeOnboardJira(CLEAN), "PROJ", tmp_path)
    assert not (tmp_path / "plan.yaml").exists()
    assert not (tmp_path / ".taskship" / "state.json").exists()


def test_a1_search_paginates_all_pages():
    pages = [
        {"issues": [{"key": "PROJ-1"}], "nextPageToken": "tok"},
        {"issues": [{"key": "PROJ-2"}]},  # no token → last page
    ]
    calls = {"n": 0}

    def handler(request):
        page = pages[calls["n"]]
        calls["n"] += 1
        return httpx.Response(200, json=page)

    from taskship.jira import JiraClient
    http = httpx.Client(transport=httpx.MockTransport(handler),
                        base_url="https://x.atlassian.net", auth=("e", "t"))
    client = JiraClient("https://x.atlassian.net", "e", "t", "PROJ", client=http)
    issues = client.search_project_issues()
    assert [i["key"] for i in issues] == ["PROJ-1", "PROJ-2"]
    assert calls["n"] == 2


# --- REQ-ONBOARD-002 -------------------------------------------------------

def test_a1_records_every_imported_node_in_state(tmp_path):
    result = onboard_project(FakeOnboardJira(CLEAN), "PROJ", tmp_path)
    state = StateStore(tmp_path / ".taskship" / "state.json")
    assert state.key("proj-1") == "PROJ-1"
    assert state.key("proj-1/proj-2") == "PROJ-2"
    assert state.key("proj-1/proj-2/proj-3") == "PROJ-3"
    assert result.state_entries == 4


def test_a2_sync_dry_run_after_onboard_reports_zero_creates(tmp_path):
    onboard_project(FakeOnboardJira(CLEAN), "PROJ", tmp_path)
    plan, _raw = load_plan(tmp_path / "plan.yaml")
    state = StateStore(tmp_path / ".taskship" / "state.json")

    report = reconcile(plan, FakeOnboardJira(CLEAN), state, dry_run=True)
    assert report.created == []                    # the adoption guarantee
    assert set(report.skipped) == {
        "proj-1", "proj-1/proj-2", "proj-1/proj-2/proj-3", "proj-1/proj-2/proj-4"
    }


def test_a2_sync_dry_run_zero_creates_via_cli(tmp_path, monkeypatch):
    monkeypatch.setattr("taskship.cli._build_client",
                        lambda cfg: FakeOnboardJira(CLEAN))
    runner = CliRunner()
    assert runner.invoke(cli, ["--dir", str(tmp_path), "onboard", "PROJ"]).exit_code == 0
    out = runner.invoke(cli, ["--dir", str(tmp_path), "sync", "--dry-run"])
    assert out.exit_code == 0, out.output
    assert "created 0" in out.output


# --- REQ-ONBOARD-003 -------------------------------------------------------

def test_a1_type_inference_keeps_labeled_type_else_imported(tmp_path):
    assert infer_task_type(["taskship:type:biz-spec"], None) == ("biz-spec", False)
    assert infer_task_type(["random"], None) == ("imported", False)
    # a kept type whose template needs fields we can't recover is downgraded
    assert infer_task_type(["taskship:type:test-case"], None) == ("imported", True)


def test_a1_imported_and_kept_types_in_plan(tmp_path):
    onboard_project(FakeOnboardJira(CLEAN), "PROJ", tmp_path)
    plan, _raw = load_plan(tmp_path / "plan.yaml")
    tasks = {t.id: t for t in plan.epics[0].stories[0].tasks}
    assert tasks["proj-3"].type == "imported"      # no taskship:type label
    assert tasks["proj-4"].type == "biz-spec"      # kept from label


def test_a2_imported_task_payload_has_no_description(tmp_path):
    onboard_project(FakeOnboardJira(CLEAN), "PROJ", tmp_path)
    plan, _raw = load_plan(tmp_path / "plan.yaml")
    payloads = {p.external_id: p for p in build_payloads(plan)}

    imported = payloads["proj-1/proj-2/proj-3"]
    assert imported.description is None
    assert "description" not in imported.fields    # never patched by sync
    # a non-imported task still renders a description
    assert payloads["proj-1/proj-2/proj-4"].description is not None


def test_a3_imported_task_still_syncs_structural_fields(tmp_path):
    onboard_project(FakeOnboardJira(CLEAN), "PROJ", tmp_path)
    plan, _raw = load_plan(tmp_path / "plan.yaml")
    payloads = {p.external_id: p for p in build_payloads(plan)}
    imported = payloads["proj-1/proj-2/proj-3"]

    assert imported.summary == "Define requirements"
    assert imported.parent_external_id == "proj-1"
    assert "taskship:type:imported" in imported.labels
    assert "summary" in imported.fields and "labels" in imported.fields


# --- REQ-ONBOARD-004 -------------------------------------------------------

def test_a1_refuses_when_plan_exists_and_leaves_files_untouched(tmp_path):
    (tmp_path / "plan.yaml").write_text("product: keep\njira_project: OLD\n")
    state_path = tmp_path / ".taskship" / "state.json"
    state_path.parent.mkdir()
    state_path.write_text('{"old": {"jira": "OLD-1", "hash": "x", "fields": {}}}')

    with pytest.raises(OnboardError) as exc:
        onboard_project(FakeOnboardJira(CLEAN), "PROJ", tmp_path)
    assert "one-time" in str(exc.value)
    assert str(tmp_path / "plan.yaml") in str(exc.value)     # names what's at risk
    assert (tmp_path / "plan.yaml").read_text().startswith("product: keep")
    assert "OLD-1" in state_path.read_text()                 # state unchanged


def test_a1_force_replaces_existing_plan_and_state(tmp_path):
    (tmp_path / "plan.yaml").write_text("product: keep\njira_project: OLD\n")
    result = onboard_project(FakeOnboardJira(CLEAN), "PROJ", tmp_path, force=True)
    assert result.replaced is True
    plan, _raw = load_plan(tmp_path / "plan.yaml")
    assert plan.jira_project == "PROJ"
    state = StateStore(tmp_path / ".taskship" / "state.json")
    assert state.key("old") is None                          # stale state gone
    assert state.key("proj-1") == "PROJ-1"


def test_a2_interrupted_import_writes_neither_file(tmp_path):
    with pytest.raises(RuntimeError):
        onboard_project(BoomJira(), "PROJ", tmp_path)
    assert not (tmp_path / "plan.yaml").exists()
    assert not (tmp_path / ".taskship" / "state.json").exists()


# --- REQ-ONBOARD-005 -------------------------------------------------------

def test_a1_summary_has_counts_tree_and_next_steps(tmp_path):
    result = onboard_project(FakeOnboardJira(CLEAN), "PROJ", tmp_path)
    text = format_onboard_summary(result)
    assert "Imported 1 epic(s), 1 story(ies), 2 task(s)" in text
    assert "Checkout revamp" in text and "Guest flow" in text   # the review tree
    assert "sync --dry-run" in text
    assert "prune plan.yaml" in text


def test_a2_summary_flags_likely_noise(tmp_path):
    issues = [
        raw("PROJ-1", "Epic", "Empty epic"),                # zero open stories
        raw("PROJ-2", "Story", "Done story", parent="PROJ-1",
            status="Done", category="done"),                # done leftover
        raw("PROJ-3", "Epic", "Live epic"),
        raw("PROJ-4", "Story", "Live story", parent="PROJ-3"),
    ]
    result = onboard_project(FakeOnboardJira(issues), "PROJ", tmp_path)
    text = format_onboard_summary(result)
    assert "Empty epic" in result.empty_epics
    assert "PROJ-2" in result.done_leftovers
    assert "LIKELY NOISE" in text
