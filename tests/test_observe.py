"""REQ-DOORS-002/006 — `taskship observe` appends to the intake lane, plan-only.

A1: observe appends one ops-observation task; flags fill the template fields.
A2: the intake lane (ops-intake epic + kind:ops story) is created on first use
    without modifying any existing node.
A3: no Jira calls, no JIRA_* env needed (a pure session/CLI edit).
A4: two observes append two distinct tasks with unique ids.
A5: the result still validates; an invalid write is rejected, file untouched.
"""
import pytest
from click.testing import CliRunner

from taskship.cli import cli
from taskship.identity import INTAKE_EPIC_ID, INTAKE_STORY_ID
from taskship.plan_io import load_plan
from taskship.session import TaskShipSession

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


def test_a1_a2_observe_creates_lane_and_appends(tmp_path):
    s = _session(tmp_path)
    before_epics = len(s.get_plan()["epics"])
    result = s.observe("Checkout 500s spiking", impact="guests blocked",
                       evidence="datadog#42")
    assert result["lane_created"] is True

    plan = s.get_plan()
    # existing epic untouched; a new intake epic was appended (A2).
    assert plan["epics"][0]["id"] == "guest-checkout"
    assert plan["epics"][0]["stories"][0]["tasks"] == []
    assert len(plan["epics"]) == before_epics + 1
    intake = plan["epics"][-1]
    assert intake["id"] == INTAKE_EPIC_ID
    story = intake["stories"][0]
    assert story["id"] == INTAKE_STORY_ID and story["kind"] == "ops"

    task = story["tasks"][0]
    assert task["type"] == "ops-observation"
    assert task["title"] == "Checkout 500s spiking"
    assert task["fields"]["observation"] == "Checkout 500s spiking"
    assert task["fields"]["impact"] == "guests blocked"
    assert task["fields"]["evidence"] == "datadog#42"


def test_a2_second_observe_reuses_lane(tmp_path):
    s = _session(tmp_path)
    first = s.observe("A")
    second = s.observe("B")
    assert first["lane_created"] is True
    assert second["lane_created"] is False
    intake = s.get_plan()["epics"][-1]
    assert len(intake["stories"]) == 1


def test_a4_two_observes_distinct_unique_ids(tmp_path):
    s = _session(tmp_path)
    r1 = s.observe("Same title")
    r2 = s.observe("Same title")
    tasks = s.get_plan()["epics"][-1]["stories"][0]["tasks"]
    assert len(tasks) == 2
    ids = [t["id"] for t in tasks]
    assert ids[0] != ids[1]
    assert r1["id"] != r2["id"]


def test_a5_result_validates_and_roundtrips(tmp_path):
    s = _session(tmp_path)
    s.observe("Latency creep", impact="p95 up 30%")
    s.save()
    reloaded, _raw = load_plan(tmp_path / "plan.yaml")  # validates on load
    intake = reloaded.epics[-1]
    assert intake.id == INTAKE_EPIC_ID
    assert intake.stories[0].tasks[0].fields["impact"] == "p95 up 30%"


def test_a3_cli_observe_no_jira_env(tmp_path, monkeypatch):
    (tmp_path / "plan.yaml").write_text(SAMPLE)
    # Ensure no JIRA_* credentials are present — the command must not need them.
    monkeypatch.delenv("JIRA_BASE_URL", raising=False)
    monkeypatch.delenv("JIRA_EMAIL", raising=False)
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    result = CliRunner().invoke(
        cli, ["--dir", str(tmp_path), "observe", "Disk 90% full",
              "--impact", "ingest stalls", "--evidence", "graph#7"]
    )
    assert result.exit_code == 0, result.output
    plan, _ = load_plan(tmp_path / "plan.yaml")
    task = plan.epics[-1].stories[0].tasks[0]
    assert task.title == "Disk 90% full"
    assert task.fields["impact"] == "ingest stalls"


def test_cli_observe_requires_plan(tmp_path):
    result = CliRunner().invoke(cli, ["--dir", str(tmp_path), "observe", "x"])
    assert result.exit_code != 0
    assert "no plan.yaml" in result.output
