"""MCP server — the agent front door (REQ-TS-013).

A thin wrapper that exposes the same :class:`~taskship.session.TaskShipSession`
operations the CLI drives, so an agent can plan conversationally and keep Jira
in sync over the identical engine. Because every tool reads/mutates the same
plan-as-code a human edits, nothing is a black box: an agent's changes are
reviewable in the same ``plan.yaml``.

Run with ``taskship-mcp`` (requires the optional ``mcp`` dependency:
``pip install 'taskship[mcp]'``).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from .session import TaskShipSession

mcp = FastMCP("taskship")
_session: Optional[TaskShipSession] = None


def _s() -> TaskShipSession:
    global _session
    if _session is None:
        _session = TaskShipSession(Path.cwd())
    return _session


@mcp.tool()
def get_plan() -> dict:
    """Return the current plan-as-code as structured data."""
    return _s().get_plan()


@mcp.tool()
def update_plan(patch: dict) -> dict:
    """Shallow-merge top-level plan fields; returns the updated plan."""
    return _s().update_plan(patch)


@mcp.tool()
def add_epic(title: str, id: Optional[str] = None,
             summary: Optional[str] = None) -> str:
    """Add an epic; returns its local id."""
    return _s().add_epic(title, id=id, summary=summary)


@mcp.tool()
def add_story(epic_id: str, title: str, id: Optional[str] = None,
              kind: Optional[str] = None) -> str:
    """Add a story under an epic (kind='devops' for a DevOps story)."""
    return _s().add_story(epic_id, title, id=id, kind=kind)


@mcp.tool()
def add_task(epic_id: str, story_id: str, type: str, title: str,
             subtype: Optional[str] = None, metrics: Optional[dict] = None,
             id: Optional[str] = None) -> str:
    """Add a typed task under a story."""
    return _s().add_task(epic_id, story_id, type=type, title=title,
                         subtype=subtype, metrics=metrics, id=id)


@mcp.tool()
def sync_to_jira(dry_run: bool = False) -> dict:
    """Reconcile the plan into Jira idempotently; returns the diff."""
    result = _s().sync_to_jira(dry_run=dry_run)
    if not dry_run:
        _s().save()
    return result


@mcp.tool()
def get_board_status() -> list[dict]:
    """Reverse sync — live status back from the board."""
    return _s().get_board_status()


@mcp.tool()
def observe(title: str, impact: Optional[str] = None,
            evidence: Optional[str] = None, action: Optional[str] = None) -> dict:
    """Append a production observation to the ops intake lane (plan-only).

    @implements REQ-DOORS-006 — same engine as `taskship observe`; returns the
    affected node id(s) and whether the intake lane was just created.
    """
    result = _s().observe(title, impact=impact, evidence=evidence, action=action)
    _s().save()
    return result


@mcp.tool()
def derive_testplan() -> dict:
    """Derive one e2e test-case task per non-ops story, idempotently (plan-only).

    @implements REQ-DOORS-006 — same engine as `taskship testplan`; returns the
    node ids added and skipped.
    """
    result = _s().derive_testplan()
    _s().save()
    return result


@mcp.tool()
def raise_issue(title: str, story: Optional[str] = None,
                epic: Optional[str] = None, expected: Optional[str] = None,
                actual: Optional[str] = None, steps: Optional[str] = None,
                severity: Optional[str] = None, environment: Optional[str] = None,
                test: Optional[str] = None) -> dict:
    """Park a UAT issue under the story it was found against (plan-only).

    @implements REQ-DOORS-009 — same engine as `taskship raise`; exactly one of
    `story`/`epic` must be given. Returns the new task id and the story it was
    parked under (`<epic-id>-uat` for a cross-story `epic` finding).
    """
    result = _s().raise_issue(
        title, story=story, epic=epic, expected=expected, actual=actual,
        steps=steps, severity=severity, environment=environment, test=test,
    )
    _s().save()
    return result


@mcp.tool()
def decompose_brief(text: str) -> dict:
    """Decompose a product brief into a structured plan (no Jira writes)."""
    from .decompose import decompose_brief as _decompose
    return _decompose(text)


def main() -> None:  # pragma: no cover
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
