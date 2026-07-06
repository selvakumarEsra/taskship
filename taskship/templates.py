"""Task-type templates → Atlassian Document Format (REQ-TS-004).

Each task ``type`` has a versioned template (a YAML file) describing the
sections its Jira description carries and the labels it sets. Templates enforce
completeness: a template whose required fields are unmet refuses to render
rather than emit a blank ticket. Built-in templates ship under
``taskship/builtin_templates/``; a team can point ``templates_dir`` at a forked
directory to override them without touching TaskShip's core.

The renderer emits ADF — the JSON document format Jira Cloud's REST v3 accepts
for issue descriptions: ``{"version": 1, "type": "doc", "content": [...]}``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from ruamel.yaml import YAML

from .model import Task

_BUILTIN_DIR = Path(__file__).parent / "builtin_templates"
_yaml = YAML(typ="safe")


class TemplateError(Exception):
    """Raised when a template refuses to render an incomplete task."""


def _load_template(task_type: str, templates_dir: Optional[Path]) -> dict:
    """Load the template for ``task_type``; a forked dir overrides the built-in.

    @implements REQ-TS-004
    """
    for base in (templates_dir, _BUILTIN_DIR):
        if base is None:
            continue
        path = Path(base) / f"{task_type}.yaml"
        if path.exists():
            with path.open("r", encoding="utf-8") as fh:
                return _yaml.load(fh)
    raise TemplateError(f"no template found for task type '{task_type}'")


# --- ADF node builders -----------------------------------------------------

def _text(value: str) -> dict:
    return {"type": "text", "text": value}


def _heading(value: str, level: int = 3) -> dict:
    return {"type": "heading", "attrs": {"level": level}, "content": [_text(value)]}


def _paragraph(value: str) -> dict:
    return {"type": "paragraph", "content": [_text(value)]}


def _doc(content: list[dict]) -> dict:
    return {"version": 1, "type": "doc", "content": content}


# --- rendering -------------------------------------------------------------

def _check_required(task: Task, template: dict) -> None:
    """Refuse to render when required content is missing (A2)."""
    for key in template.get("required", []):
        if key not in task.fields or task.fields[key] in (None, ""):
            raise TemplateError(
                f"task '{task.id or task.title}' ({task.type}) is missing "
                f"required field '{key}'"
            )
    # Subtype-driven metric requirement (perf).
    if task.subtype in template.get("requires_metrics", []):
        if task.metrics is None:
            raise TemplateError(
                f"task '{task.id or task.title}' is {task.type}/{task.subtype} "
                "and must define metrics (baseline + target)"
            )


def render_labels(task: Task, templates_dir: Optional[Union[str, Path]] = None) -> list[str]:
    """Labels a task carries into Jira: template labels + type/subtype (A4).

    @implements REQ-TS-004
    """
    template = _load_template(task.type, _as_path(templates_dir))
    labels = list(template.get("labels", []))
    type_label = f"taskship:type:{task.type}"
    if type_label not in labels:
        labels.append(type_label)
    if task.subtype:
        labels.append(f"taskship:subtype:{task.subtype}")
    return labels


def render_adf(task: Task, templates_dir: Optional[Union[str, Path]] = None) -> dict:
    """Render a task's Jira description as an ADF document.

    @implements REQ-TS-004

    Refuses (``TemplateError``) if the template's required fields — including a
    perf subtype's metrics — are unmet. Otherwise emits one heading per section
    with the task's content, or a placeholder prompt when the content is absent.
    """
    template = _load_template(task.type, _as_path(templates_dir))
    _check_required(task, template)

    content: list[dict] = []
    for section in template.get("sections", []):
        content.append(_heading(section["heading"]))
        if section.get("metrics"):
            m = task.metrics
            body = f"{m.baseline} → {m.target}" if m else "_no metric_"
            content.append(_paragraph(body))
            continue
        field = section.get("field")
        value = task.fields.get(field) if field else None
        if value:
            content.append(_paragraph(str(value)))
        else:
            content.append(_paragraph(section.get("placeholder", "_TBD_")))
    return _doc(content)


def _as_path(templates_dir: Optional[Union[str, Path]]) -> Optional[Path]:
    return Path(templates_dir) if templates_dir is not None else None
