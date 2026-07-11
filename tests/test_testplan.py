"""REQ-DOORS-004/005/006 — `taskship testplan` derives idempotent test cases.

A1: every non-ops story gets exactly one test-case task, id <story-id>-e2e,
    scope pre-filled from the story title.
A2: a re-run changes nothing — no duplicate, no modification of edited cases.
A3: a story added after a run gets its case next run; ops stories never do.
A4: plan-only (no Jira) and the result validates against the schema.
"""
from click.testing import CliRunner

from taskship.cli import cli
from taskship.payload import build_payloads
from taskship.plan_io import load_plan
from taskship.session import TaskShipSession

SAMPLE = (
    "product: Checkout\n"
    "jira_project: CHK\n"
    "epics:\n"
    "  - id: guest-checkout\n"
    "    title: Guest checkout\n"
    "    stories:\n"
    "      - id: guest-flow\n"
    "        title: Guest checkout flow\n"
    "        tasks:\n"
    "          - id: biz-1\n"
    "            title: Define requirements\n"
    "            type: biz-spec\n"
    "      - id: ops-lane\n"
    "        title: Live incidents\n"
    "        kind: ops\n"
    "        tasks: []\n"
)


def _session(tmp_path):
    (tmp_path / "plan.yaml").write_text(SAMPLE)
    return TaskShipSession(tmp_path)


def _story_tasks(plan_dict, story_id):
    for epic in plan_dict["epics"]:
        for story in epic["stories"]:
            if story.get("id") == story_id:
                return story["tasks"]
    raise AssertionError(f"no story {story_id}")


def test_a1_derives_one_test_case_per_nonops_story(tmp_path):
    s = _session(tmp_path)
    result = s.derive_testplan()
    assert result["added"] == ["guest-checkout/guest-flow/guest-flow-e2e"]

    tasks = _story_tasks(s.get_plan(), "guest-flow")
    tc = [t for t in tasks if t["type"] == "test-case"]
    assert len(tc) == 1
    assert tc[0]["id"] == "guest-flow-e2e"
    assert tc[0]["fields"]["scope"] == "Guest checkout flow"
    # ops story never gets one (A3).
    assert _story_tasks(s.get_plan(), "ops-lane") == []


def test_a2_rerun_is_idempotent(tmp_path):
    s = _session(tmp_path)
    s.derive_testplan()
    # a human edits the derived case; a re-run must not touch it.
    tasks = _story_tasks(s.get_plan(), "guest-flow")
    for t in s.raw["epics"][0]["stories"][0]["tasks"]:
        if t.get("id") == "guest-flow-e2e":
            t["fields"]["scope"] = "hand-edited scope"
    result = s.derive_testplan()
    assert result["added"] == []
    assert result["skipped"] == ["guest-checkout/guest-flow/guest-flow-e2e"]
    tc = [t for t in _story_tasks(s.get_plan(), "guest-flow") if t["type"] == "test-case"]
    assert len(tc) == 1
    assert tc[0]["fields"]["scope"] == "hand-edited scope"  # untouched


def test_a3_new_story_gets_case_next_run(tmp_path):
    s = _session(tmp_path)
    s.derive_testplan()
    s.add_story("guest-checkout", title="Returns flow", id="returns")
    result = s.derive_testplan()
    assert result["added"] == ["guest-checkout/returns/returns-e2e"]
    assert "guest-checkout/guest-flow/guest-flow-e2e" in result["skipped"]


def test_a3_story_without_id_uses_slug(tmp_path):
    (tmp_path / "plan.yaml").write_text(
        "product: P\njira_project: PR\nepics:\n"
        "  - id: e\n    title: E\n    stories:\n"
        "      - title: Payment Retry Path\n        tasks: []\n"
    )
    s = TaskShipSession(tmp_path)
    result = s.derive_testplan()
    assert result["added"] == ["e/payment-retry-path/payment-retry-path-e2e"]


def test_doors004_a3_test_case_carries_source_story_label(tmp_path):
    s = _session(tmp_path)
    s.derive_testplan()
    s.save()
    plan, _ = load_plan(tmp_path / "plan.yaml")
    payloads = {p.external_id: p for p in build_payloads(plan)}
    tc = payloads["guest-checkout/guest-flow/guest-flow-e2e"]
    assert "taskship:type:test-case" in tc.labels
    assert "taskship:story:guest-flow" in tc.labels


def test_a4_cli_testplan_validates_and_writes(tmp_path):
    (tmp_path / "plan.yaml").write_text(SAMPLE)
    result = CliRunner().invoke(cli, ["--dir", str(tmp_path), "testplan"])
    assert result.exit_code == 0, result.output
    assert "added 1" in result.output
    plan, _ = load_plan(tmp_path / "plan.yaml")  # validates on load
    tc = [t for t in plan.epics[0].stories[0].tasks if t.type == "test-case"]
    assert len(tc) == 1
