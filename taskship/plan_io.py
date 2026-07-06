"""Comment-preserving load/dump for ``plan.yaml`` (REQ-TS-001).

Loading validates the plan and returns both the typed :class:`Plan` and the raw
ruamel round-trip document. Keeping the raw ``CommentedMap`` is what makes the
round-trip lossless (A1): the author's fields, ordering, and comments are
serialized back verbatim, while the typed model carries the validated view used
by the rest of TaskShip.

Validation happens on load, before any write can occur, so an invalid plan is
rejected with no partial write (A2).
"""
from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML

from .model import Plan, PlanValidationError

# A single round-trip ("rt") parser preserves comments, ordering, and styling.
_yaml = YAML(typ="rt")
_yaml.preserve_quotes = True
# Indent block sequences under their key (dash at offset 2, content at 4) so
# writeback matches the conventional plan.yaml layout.
_yaml.indent(mapping=2, sequence=4, offset=2)


def load_plan(path: str | Path) -> tuple[Plan, object]:
    """Read and validate a plan file.

    @implements REQ-TS-001

    Returns a ``(plan, raw)`` tuple: ``plan`` is the validated :class:`Plan`,
    ``raw`` is the ruamel round-trip document to hand back to :func:`dump_plan`
    for lossless writeback.

    Raises :class:`PlanValidationError` if the plan is malformed; nothing is
    written in that case.
    """
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        raw = _yaml.load(fh)

    # Validate the raw mapping. On failure this raises before any writeback.
    plan = Plan.from_mapping(raw)
    return plan, raw


def dump_plan(raw: object, path: str | Path) -> None:
    """Serialize a round-trip document back to ``path``, preserving comments.

    @implements REQ-TS-001

    ``raw`` is the document returned by :func:`load_plan` (or an equally
    comment-carrying ``CommentedMap``). Writing the retained document rather
    than the typed model is what keeps the round-trip lossless (A1).
    """
    path = Path(path)
    with path.open("w", encoding="utf-8") as fh:
        _yaml.dump(raw, fh)


__all__ = ["load_plan", "dump_plan", "Plan", "PlanValidationError"]
