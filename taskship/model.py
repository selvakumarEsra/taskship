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
    """Base for plan nodes: forbid unknown fields so typos surface as errors.

    Cascadeable fields (REQ-TS-003) live here so every level carries them:
    ``labels`` is ``None`` when unspecified (inherit) versus ``[]`` (explicit
    empty override). ``labels_merge`` opts a node into unioning its labels with
    the inherited set instead of overriding them.
    """

    model_config = ConfigDict(extra="forbid")

    labels: Optional[list[str]] = None
    labels_merge: bool = False


class Metrics(BaseModel):
    """A measurable performance target: both endpoints are required (A3)."""

    model_config = ConfigDict(extra="forbid")

    baseline: str
    target: str


class Task(_Node):
    """A leaf work item mapped 1:1 to a Jira task-level issue.

    ``id`` is optional: when omitted, identity falls back to a deterministic
    slug of ``title`` (REQ-TS-002). Supplying an explicit ``id`` pins identity
    so the title can change freely without creating a duplicate on sync.
    """

    id: Optional[str] = None
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
    """A story groups tasks under an epic (Jira level 0).

    ``id`` is optional; identity falls back to a slug of ``title`` when omitted
    (REQ-TS-002). ``kind`` flags a DevOps story so its work lives in its own
    swimlane.
    """

    id: Optional[str] = None
    title: str
    kind: Optional[str] = None
    tasks: list[Task] = []


class Epic(_Node):
    """An epic groups stories under the product (Jira level 1).

    ``id`` is optional; identity falls back to a slug of ``title`` when omitted
    (REQ-TS-002).
    """

    id: Optional[str] = None
    title: str
    stories: list[Story] = []


class Defaults(BaseModel):
    """Plan-wide defaults — the root of the field cascade (REQ-TS-003)."""

    model_config = ConfigDict(extra="forbid")

    labels: list[str] = []


class Plan(BaseModel):
    """The whole plan: product → epics → stories → tasks.

    The root of the cascade: ``defaults`` supplies the fields epics/stories/
    tasks inherit unless they override them (REQ-TS-003).
    """

    model_config = ConfigDict(extra="forbid")

    product: str
    jira_project: str
    defaults: Defaults = Defaults()
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
