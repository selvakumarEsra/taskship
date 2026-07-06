"""Schema validation tests for REQ-TS-001 (A2, A3)."""
import pytest

from taskship import Plan, PlanValidationError


def _base_plan():
    return {
        "product": "Acme Storefront",
        "jira_project": "STORE",
        "epics": [
            {
                "id": "guest-flow",
                "title": "Guest checkout",
                "stories": [
                    {
                        "id": "address-entry",
                        "title": "Collect shipping address",
                        "tasks": [
                            {"id": "biz-spec-1", "title": "Fields", "type": "biz-spec"}
                        ],
                    }
                ],
            }
        ],
    }


def test_valid_plan_loads():
    """Happy path: a well-formed mapping validates into a Plan."""
    plan = Plan.from_mapping(_base_plan())
    assert plan.product == "Acme Storefront"
    assert plan.jira_project == "STORE"
    assert plan.epics[0].stories[0].tasks[0].id == "biz-spec-1"


def test_epic_missing_title_rejected():
    """A2: an epic without `title` is rejected, error names the node path."""
    data = _base_plan()
    del data["epics"][0]["title"]

    with pytest.raises(PlanValidationError) as exc:
        Plan.from_mapping(data)

    assert "epics[0].title" in str(exc.value)


def test_missing_product_and_jira_project():
    """A2: top-level required fields missing are rejected by name."""
    data = _base_plan()
    del data["product"]
    del data["jira_project"]

    with pytest.raises(PlanValidationError) as exc:
        Plan.from_mapping(data)

    msg = str(exc.value)
    assert "product" in msg
    assert "jira_project" in msg


def test_perf_task_missing_metrics_rejected():
    """A3: a tech-spec/perf task without metrics is rejected, naming the task."""
    data = _base_plan()
    data["epics"][0]["stories"][0]["tasks"].append(
        {
            "id": "tech-spec-1",
            "title": "Fast autocomplete",
            "type": "tech-spec",
            "subtype": "perf",
        }
    )

    with pytest.raises(PlanValidationError) as exc:
        Plan.from_mapping(data)

    assert "tech-spec-1" in str(exc.value)


def test_perf_task_with_metrics_accepted():
    """A3: a tech-spec/perf task with baseline+target metrics validates."""
    data = _base_plan()
    data["epics"][0]["stories"][0]["tasks"].append(
        {
            "id": "tech-spec-1",
            "title": "Fast autocomplete",
            "type": "tech-spec",
            "subtype": "perf",
            "metrics": {"baseline": "p95 480ms", "target": "p95 200ms"},
        }
    )

    plan = Plan.from_mapping(data)
    task = plan.epics[0].stories[0].tasks[1]
    assert task.metrics.baseline == "p95 480ms"
    assert task.metrics.target == "p95 200ms"
