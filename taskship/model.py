"""Pydantic v2 schema for the TaskShip plan (REQ-TS-001).

The schema is the contract a ``plan.yaml`` must satisfy before TaskShip will
work with it. Validation is strict and structured: a malformed plan is rejected
with a :class:`PlanValidationError` naming the offending node path, never
silently repaired. This module is the shared validation foundation that
downstream requirements (identity, cascade, decomposition) extend.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator


class PlanValidationError(Exception):
    """Raised when a plan fails schema validation.

    Wraps pydantic's :class:`~pydantic.ValidationError`, rendering each error's
    ``loc`` tuple as a human-readable node path (e.g. ``epics[1].title``) so a
    reviewer can find the offending node directly.
    """

    def __init__(self, error: ValidationError) -> None:
        self.error = error
        super().__init__(_format_errors(error))


def _format_loc(loc: tuple) -> str:
    """Render a pydantic ``loc`` tuple as a node path like ``epics[0].title``."""
    parts: list[str] = []
    for item in loc:
        if isinstance(item, int):
            parts.append(f"[{item}]")
        else:
            parts.append(f".{item}" if parts else str(item))
    return "".join(parts)


def _format_errors(error: ValidationError) -> str:
    lines = [
        f"{_format_loc(e['loc'])}: {e['msg']}" for e in error.errors()
    ]
    return "plan validation failed:\n" + "\n".join(f"  - {line}" for line in lines)


class _Node(BaseModel):
    """Base for plan nodes: forbid unknown fields so typos surface as errors."""

    model_config = ConfigDict(extra="forbid")


class Metrics(_Node):
    """A measurable performance target: both endpoints are required (A3)."""

    baseline: str
    target: str


class Task(_Node):
    """A leaf work item mapped 1:1 to a Jira task-level issue."""

    id: str
    title: str
    type: str
    subtype: Optional[str] = None
    metrics: Optional[Metrics] = None

    @model_validator(mode="after")
    def _require_metrics_for_perf(self) -> "Task":
        """A3: a ``tech-spec`` task subtyped ``perf`` MUST carry metrics."""
        if self.type == "tech-spec" and self.subtype == "perf" and self.metrics is None:
            raise ValueError(
                f"task '{self.id}' is tech-spec/perf and must define "
                "metrics (baseline + target)"
            )
        return self


class Story(_Node):
    """A story groups tasks under an epic (Jira level 0)."""

    id: str
    title: str
    tasks: list[Task] = []


class Epic(_Node):
    """An epic groups stories under the product (Jira level 1)."""

    id: str
    title: str
    stories: list[Story] = []


class Plan(_Node):
    """The whole plan: product → epics → stories → tasks."""

    product: str
    jira_project: str
    epics: list[Epic] = []

    @classmethod
    def from_mapping(cls, data: object) -> "Plan":
        """Validate a plain mapping into a ``Plan``.

        @implements REQ-TS-001

        Converts pydantic's :class:`ValidationError` into a
        :class:`PlanValidationError` so callers see node-path messages and a
        single, stable exception type.
        """
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            raise PlanValidationError(exc) from exc
