"""REQ-DOORS-008/009 — `taskship raise` parks a UAT issue under its story.

A1: raise appends one uat-issue task under the named story; flags fill fields.
A2: the task carries a taskship:story:<story-id> label; --test adds a
    taskship:test:<id> label.
A3: --epic parks the issue in the epic's <epic-id>-uat fallback story, creating
    it if absent without modifying any existing node; exactly one of
    --story / --epic must be given.
A4: an unknown --story/--epic id errors naming the id; plan.yaml untouched.
A5: plan-only (no Jira, no JIRA_* env); the same title twice appends two
    distinct tasks with unique ids; the result validates against the schema.
"""
import pytest
from click.testing import CliRunner

from taskship.cli import cli
from taskship.payload import build_payloads
from taskship.plan_io import load_plan
from taskship.session import PlanEditError, TaskShipSession

SAMPLE = (
    "product: Checkout\n"
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


def _story(plan_dict, story_id):
    for epic in plan_dict["epics"]:
        for story in epic["stories"]:
            if story.get("id") == story_id:
                return story
    raise AssertionError(f"no story {story_id}")


# --- A1: raise under a story appends one uat-issue task ---------------------

def test_a1_raise_appends_uat_issue_under_story(tmp_path):
    s = _session(tmp_path)
    result = s.raise_issue(
        "Totals wrong for split shipment", story="guest-flow",
        expected="one total", actual="two totals", steps="add two carts",
        severity="high",
    )
    assert result["story"] == "guest-flow"
    assert result["added"] == [f"guest-checkout/guest-flow/{result['id']}"]

    tasks = _story(s.get_plan(), "guest-flow")["tasks"]
    assert len(tasks) == 1
    task = tasks[0]
    assert task["type"] == "uat-issue"
    assert task["title"] == "Totals wrong for split shipment"
    assert task["fields"]["expected"] == "one total"
    assert task["fields"]["actual"] == "two totals"
    assert task["fields"]["steps"] == "add two carts"
    assert task["fields"]["severity"] == "high"


# --- A2: story label always; test label when --test given -------------------

def test_a2_carries_story_label(tmp_path):
    s = _session(tmp_path)
    s.raise_issue("x", story="guest-flow", expected="a", actual="b")
    s.save()
    plan, _ = load_plan(tmp_path / "plan.yaml")
    payloads = {p.external_id: p for p in build_payloads(plan)}
    tid = _story(s.get_plan(), "guest-flow")["tasks"][0]["id"]
    labels = payloads[f"guest-checkout/guest-flow/{tid}"].labels
    assert "taskship:type:uat-issue" in labels
    assert "bug" in labels
    assert "taskship:story:guest-flow" in labels
    assert "taskship:triage" not in labels


def test_a2_test_flag_adds_test_label(tmp_path):
    s = _session(tmp_path)
    s.raise_issue("x", story="guest-flow", expected="a", actual="b",
                  test="guest-flow-e2e")
    s.save()
    plan, _ = load_plan(tmp_path / "plan.yaml")
    payloads = {p.external_id: p for p in build_payloads(plan)}
    tid = _story(s.get_plan(), "guest-flow")["tasks"][0]["id"]
    labels = payloads[f"guest-checkout/guest-flow/{tid}"].labels
    assert "taskship:test:guest-flow-e2e" in labels


# --- A3: --epic fallback story + exactly-one guard --------------------------

def test_a3_epic_creates_uat_fallback_story(tmp_path):
    s = _session(tmp_path)
    before = _story(s.get_plan(), "guest-flow")["tasks"]
    result = s.raise_issue("Cross-story regression", epic="guest-checkout",
                           expected="a", actual="b")
    assert result["story"] == "guest-checkout-uat"
    assert result["story_created"] is True

    plan = s.get_plan()
    # existing story untouched (A3).
    assert _story(plan, "guest-flow")["tasks"] == before
    fallback = _story(plan, "guest-checkout-uat")
    assert fallback["tasks"][0]["type"] == "uat-issue"


def test_a3_epic_reuses_existing_fallback_story(tmp_path):
    s = _session(tmp_path)
    first = s.raise_issue("one", epic="guest-checkout", expected="a", actual="b")
    second = s.raise_issue("two", epic="guest-checkout", expected="a", actual="b")
    assert first["story_created"] is True
    assert second["story_created"] is False
    fallback = _story(s.get_plan(), "guest-checkout-uat")
    assert len(fallback["tasks"]) == 2


def test_a3_requires_exactly_one_of_story_or_epic(tmp_path):
    s = _session(tmp_path)
    with pytest.raises(PlanEditError):
        s.raise_issue("x", expected="a", actual="b")  # neither
    with pytest.raises(PlanEditError):
        s.raise_issue("x", story="guest-flow", epic="guest-checkout",
                      expected="a", actual="b")  # both
    # neither/both left the plan untouched.
    assert _story(s.get_plan(), "guest-flow")["tasks"] == []


# --- A4: unknown ids error naming the id, file untouched --------------------

def test_a4_unknown_story_errors_and_leaves_file_untouched(tmp_path):
    s = _session(tmp_path)
    before = (tmp_path / "plan.yaml").read_text()
    with pytest.raises(PlanEditError) as exc:
        s.raise_issue("x", story="nope", expected="a", actual="b")
    assert "nope" in str(exc.value)
    # nothing written by the failed engine call.
    assert (tmp_path / "plan.yaml").read_text() == before


def test_a4_unknown_epic_errors_naming_id(tmp_path):
    s = _session(tmp_path)
    with pytest.raises(PlanEditError) as exc:
        s.raise_issue("x", epic="nope", expected="a", actual="b")
    assert "nope" in str(exc.value)


def test_a4_cli_unknown_story_leaves_file_untouched(tmp_path):
    (tmp_path / "plan.yaml").write_text(SAMPLE)
    before = (tmp_path / "plan.yaml").read_text()
    result = CliRunner().invoke(
        cli, ["--dir", str(tmp_path), "raise", "x", "--story", "nope"]
    )
    assert result.exit_code != 0
    assert "nope" in result.output
    assert (tmp_path / "plan.yaml").read_text() == before


# --- A5: event semantics, plan-only, validates ------------------------------

def test_a5_same_title_twice_distinct_unique_ids(tmp_path):
    s = _session(tmp_path)
    r1 = s.raise_issue("Same title", story="guest-flow", expected="a", actual="b")
    r2 = s.raise_issue("Same title", story="guest-flow", expected="a", actual="b")
    assert r1["id"] != r2["id"]
    tasks = _story(s.get_plan(), "guest-flow")["tasks"]
    assert len(tasks) == 2
    assert tasks[0]["id"] != tasks[1]["id"]


def test_a5_result_validates_and_roundtrips(tmp_path):
    s = _session(tmp_path)
    s.raise_issue("Latency in checkout", story="guest-flow",
                  expected="fast", actual="slow")
    s.save()
    reloaded, _raw = load_plan(tmp_path / "plan.yaml")  # validates on load
    task = _story(reloaded.model_dump(), "guest-flow")["tasks"][0]
    assert task["fields"]["actual"] == "slow"


def test_a5_cli_raise_no_jira_env(tmp_path, monkeypatch):
    (tmp_path / "plan.yaml").write_text(SAMPLE)
    monkeypatch.delenv("JIRA_BASE_URL", raising=False)
    monkeypatch.delenv("JIRA_EMAIL", raising=False)
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    result = CliRunner().invoke(
        cli, ["--dir", str(tmp_path), "raise", "Broken coupon",
              "--story", "guest-flow", "--expected", "20% off",
              "--actual", "no discount"]
    )
    assert result.exit_code == 0, result.output
    plan, _ = load_plan(tmp_path / "plan.yaml")
    task = _story(plan.model_dump(), "guest-flow")["tasks"][0]
    assert task["title"] == "Broken coupon"
    assert task["fields"]["actual"] == "no discount"


def test_a3_cli_epic_fallback_creation(tmp_path):
    (tmp_path / "plan.yaml").write_text(SAMPLE)
    result = CliRunner().invoke(
        cli, ["--dir", str(tmp_path), "raise", "Cross-story bug",
              "--epic", "guest-checkout", "--expected", "a", "--actual", "b"]
    )
    assert result.exit_code == 0, result.output
    plan, _ = load_plan(tmp_path / "plan.yaml")
    fallback = _story(plan.model_dump(), "guest-checkout-uat")
    assert fallback["tasks"][0]["type"] == "uat-issue"


def test_cli_raise_requires_exactly_one(tmp_path):
    (tmp_path / "plan.yaml").write_text(SAMPLE)
    result = CliRunner().invoke(cli, ["--dir", str(tmp_path), "raise", "x"])
    assert result.exit_code != 0


def test_cli_raise_requires_plan(tmp_path):
    result = CliRunner().invoke(
        cli, ["--dir", str(tmp_path), "raise", "x", "--story", "s"]
    )
    assert result.exit_code != 0
    assert "no plan.yaml" in result.output
