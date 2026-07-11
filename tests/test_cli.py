"""REQ-TS-012 — CLI exposes init / review / sync / status over the core engine.

A1: init scaffolds plan.yaml, templates/, and .taskship/.
A2: review renders the epic → story → task tree.
A3: sync (and --dry-run) invoke the same reconcile engine → same decisions as
    a direct reconcile() call for the same plan.
A4: status renders the plan-vs-reality view.
"""
import json

from click.testing import CliRunner

from taskship import Plan
from taskship.cli import cli
from taskship.state import StateStore
from taskship.reconcile import reconcile

SAMPLE_PLAN = (
    "product: Checkout Revamp\n"
    "jira_project: CHK\n"
    "defaults:\n"
    "  labels: [checkout]\n"
    "epics:\n"
    "  - id: guest-checkout\n"
    "    title: One-click guest checkout\n"
    "    stories:\n"
    "      - id: guest-flow\n"
    "        title: Guest checkout flow\n"
    "        tasks:\n"
    "          - id: biz-1\n"
    "            title: Define requirements\n"
    "            type: biz-spec\n"
)


def test_a1_init_scaffolds_project(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["--dir", str(tmp_path), "init"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "plan.yaml").exists()
    assert (tmp_path / "templates").is_dir()
    assert (tmp_path / ".taskship").is_dir()
    # the scaffolded plan is itself valid
    from taskship.plan_io import load_plan
    load_plan(tmp_path / "plan.yaml")
    # every built-in template — including the ops/test doors — is forked in place.
    forked = tmp_path / "templates"
    assert (forked / "ops-observation.yaml").exists()
    assert (forked / "test-case.yaml").exists()


def test_a2_review_renders_tree(tmp_path):
    (tmp_path / "plan.yaml").write_text(SAMPLE_PLAN)
    result = CliRunner().invoke(cli, ["--dir", str(tmp_path), "review"])
    assert result.exit_code == 0, result.output
    assert "One-click guest checkout" in result.output
    assert "Guest checkout flow" in result.output
    assert "Define requirements" in result.output


def test_a3_dry_run_sync_matches_direct_reconcile(tmp_path):
    (tmp_path / "plan.yaml").write_text(SAMPLE_PLAN)
    result = CliRunner().invoke(cli, ["--dir", str(tmp_path), "sync", "--dry-run"])
    assert result.exit_code == 0, result.output
    # CLI dry-run classifies the same nodes a direct reconcile would create.
    direct = reconcile(Plan.from_mapping(json_plan()), _OfflineDummy(),
                       StateStore(tmp_path / "nonexistent.json"), dry_run=True)
    for ext_id in direct.created:
        assert ext_id in result.output
    # dry-run wrote no state
    assert not (tmp_path / ".taskship" / "state.json").exists()


def test_a3_sync_reports_create(tmp_path, monkeypatch):
    (tmp_path / "plan.yaml").write_text(SAMPLE_PLAN)
    from tests.fakes import FakeJira
    fake = FakeJira()
    # Inject the fake client instead of building a real one from env.
    monkeypatch.setattr("taskship.cli._build_client", lambda cfg: fake)
    result = CliRunner().invoke(cli, ["--dir", str(tmp_path), "sync"])
    assert result.exit_code == 0, result.output
    assert len(fake.create_calls) == 3
    assert (tmp_path / ".taskship" / "state.json").exists()


def test_a4_status_renders_plan_vs_reality(tmp_path, monkeypatch):
    (tmp_path / "plan.yaml").write_text(SAMPLE_PLAN)
    from tests.fakes import FakeJira
    fake = FakeJira()
    monkeypatch.setattr("taskship.cli._build_client", lambda cfg: fake)
    CliRunner().invoke(cli, ["--dir", str(tmp_path), "sync"])  # populate state
    fake.board = {"CHK-101": {"status": "In Progress", "assignee": "alice",
                              "story_points": 5}}
    result = CliRunner().invoke(cli, ["--dir", str(tmp_path), "status"])
    assert result.exit_code == 0, result.output
    assert "In Progress" in result.output
    assert "One-click guest checkout" in result.output


def json_plan():
    return {
        "product": "Checkout Revamp", "jira_project": "CHK",
        "defaults": {"labels": ["checkout"]},
        "epics": [{"id": "guest-checkout", "title": "One-click guest checkout",
                   "stories": [{"id": "guest-flow", "title": "Guest checkout flow",
                                "tasks": [{"id": "biz-1", "title": "Define requirements",
                                           "type": "biz-spec"}]}]}],
    }


class _OfflineDummy:
    def search_by_external_id(self, external_id):
        return None
