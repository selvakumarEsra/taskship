"""REQ-TS-004 — task-type templates render ADF and refuse incomplete specs.

A1: biz-spec renders problem/user-story/acceptance/out-of-scope/open-questions.
A2: tech-spec/perf refuses without baseline+target; renders the metric when present.
A3: devops renders infra/pipeline/rollback/runbook sections.
A4: rendered output is structurally-valid ADF (version 1 doc with valid nodes).
A5: a forked template directory renders in place of the built-ins.
"""
import pytest

from taskship.model import Task, Metrics
from taskship.templates import render_adf, render_labels, TemplateError


def _headings(adf):
    return [
        "".join(c["text"] for c in node["content"])
        for node in adf["content"]
        if node["type"] == "heading"
    ]


def _is_valid_adf(adf):
    if adf.get("type") != "doc" or adf.get("version") != 1:
        return False
    if not isinstance(adf.get("content"), list):
        return False
    for node in adf["content"]:
        if "type" not in node:
            return False
        # text nodes inside blocks must carry a string
        for child in node.get("content", []):
            if child["type"] == "text" and not isinstance(child.get("text"), str):
                return False
    return True


def test_a1_biz_spec_sections_present():
    task = Task(id="b1", title="Define guest checkout requirements", type="biz-spec")
    adf = render_adf(task)
    headings = " ".join(_headings(adf)).lower()
    assert "problem" in headings
    assert "user story" in headings
    assert "acceptance" in headings
    assert "out-of-scope" in headings or "out of scope" in headings
    assert "open question" in headings


def test_a2_tech_spec_perf_refuses_without_metrics():
    # The model validator (REQ-TS-001 A3) normally blocks this at construction;
    # bypass it with model_construct to prove the TEMPLATE layer also refuses
    # (defense in depth — e.g. a Task built programmatically via the MCP path).
    task = Task.model_construct(
        id="p1", title="Payment auth p95", type="tech-spec", subtype="perf",
        metrics=None, fields={},
    )
    with pytest.raises(TemplateError) as exc:
        render_adf(task)
    assert "p1" in str(exc.value)  # error names the task


def test_a2_tech_spec_perf_renders_metric_when_present():
    task = Task(
        id="p1", title="Payment auth p95", type="tech-spec", subtype="perf",
        metrics=Metrics(baseline="480ms", target="200ms"),
    )
    adf = render_adf(task)
    text = str(adf)
    assert "480ms" in text and "200ms" in text


def test_a3_devops_sections_present():
    task = Task(id="d1", title="CI/CD for checkout-service", type="devops")
    headings = " ".join(_headings(render_adf(task))).lower()
    assert "infra" in headings
    assert "pipeline" in headings
    assert "rollback" in headings
    assert "runbook" in headings


def test_a4_rendered_output_is_valid_adf():
    for task in [
        Task(id="b", title="B", type="biz-spec"),
        Task(id="d", title="D", type="devops"),
        Task(id="p", title="P", type="tech-spec", subtype="perf",
             metrics=Metrics(baseline="1", target="2")),
    ]:
        assert _is_valid_adf(render_adf(task)), task.type


def test_a4_labels_include_type_and_subtype():
    task = Task(id="p", title="P", type="tech-spec", subtype="perf",
                metrics=Metrics(baseline="1", target="2"))
    labels = render_labels(task)
    assert "taskship:type:tech-spec" in labels
    assert "taskship:subtype:perf" in labels


def test_doors001_ops_observation_sections_and_labels():
    task = Task(id="o1", title="Checkout 500s spiking", type="ops-observation",
                fields={"observation": "5xx on /checkout", "impact": "guests blocked"})
    headings = " ".join(_headings(render_adf(task))).lower()
    assert "observation" in headings
    assert "impact" in headings
    assert "evidence" in headings
    assert "suggested action" in headings
    labels = render_labels(task)
    assert "taskship:type:ops-observation" in labels
    assert "taskship:triage" in labels


def test_doors001_ops_observation_refuses_without_required():
    # observation present, impact missing → refuse naming the missing field.
    task = Task(id="o2", title="x", type="ops-observation",
                fields={"observation": "seen"})
    with pytest.raises(TemplateError) as exc:
        render_adf(task)
    assert "impact" in str(exc.value) and "o2" in str(exc.value)


def test_doors004_test_case_sections_and_scope_required():
    task = Task(id="tc1", title="E2E regression: Guest flow", type="test-case",
                fields={"scope": "Guest checkout flow"})
    headings = " ".join(_headings(render_adf(task))).lower()
    assert "scope" in headings
    assert "precondition" in headings
    assert "steps" in headings
    assert "expected result" in headings
    assert "taskship:type:test-case" in render_labels(task)

    missing = Task(id="tc2", title="T", type="test-case")
    with pytest.raises(TemplateError) as exc:
        render_adf(missing)
    assert "scope" in str(exc.value)


def test_doors007_uat_issue_sections_and_labels():
    task = Task(id="u1", title="Totals wrong", type="uat-issue",
                fields={"expected": "one total", "actual": "two totals"})
    headings = " ".join(_headings(render_adf(task))).lower()
    assert "expected behaviour" in headings
    assert "actual behaviour" in headings
    assert "steps to reproduce" in headings
    assert "severity" in headings
    assert "environment" in headings
    labels = render_labels(task)
    assert "taskship:type:uat-issue" in labels
    assert "bug" in labels
    # UAT issues block their story; they are not ceremony triage items (A3).
    assert "taskship:triage" not in labels


def test_doors007_uat_issue_refuses_without_required():
    # expected present, actual missing → refuse naming the missing field.
    task = Task(id="u2", title="x", type="uat-issue",
                fields={"expected": "one total"})
    with pytest.raises(TemplateError) as exc:
        render_adf(task)
    assert "actual" in str(exc.value) and "u2" in str(exc.value)


def test_doors007_uat_issue_fork_overrides_builtin(tmp_path):
    forked = tmp_path / "templates"
    forked.mkdir()
    (forked / "uat-issue.yaml").write_text(
        "type: uat-issue\n"
        "version: 99\n"
        "labels: ['taskship:type:uat-issue', 'bug']\n"
        "required: []\n"
        "sections:\n"
        "  - heading: CUSTOM UAT SECTION\n"
        "    field: expected\n"
    )
    task = Task(id="u1", title="T", type="uat-issue")
    adf = render_adf(task, templates_dir=forked)
    assert "CUSTOM UAT SECTION" in " ".join(_headings(adf))


def test_doors001_ops_observation_fork_overrides_builtin(tmp_path):
    forked = tmp_path / "templates"
    forked.mkdir()
    (forked / "ops-observation.yaml").write_text(
        "type: ops-observation\n"
        "version: 99\n"
        "labels: ['taskship:type:ops-observation', 'taskship:triage']\n"
        "required: []\n"
        "sections:\n"
        "  - heading: CUSTOM OBS SECTION\n"
        "    field: observation\n"
    )
    task = Task(id="o1", title="T", type="ops-observation")
    adf = render_adf(task, templates_dir=forked)
    assert "CUSTOM OBS SECTION" in " ".join(_headings(adf))


def test_a5_forked_template_dir_overrides_builtin(tmp_path):
    forked = tmp_path / "templates"
    forked.mkdir()
    (forked / "biz-spec.yaml").write_text(
        "type: biz-spec\n"
        "version: 99\n"
        "labels: ['taskship:type:biz-spec']\n"
        "sections:\n"
        "  - heading: CUSTOM FORKED SECTION\n"
        "    field: whatever\n"
    )
    task = Task(id="b1", title="T", type="biz-spec")
    adf = render_adf(task, templates_dir=forked)
    assert "CUSTOM FORKED SECTION" in " ".join(_headings(adf))
