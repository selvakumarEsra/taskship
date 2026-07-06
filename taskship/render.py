"""Terminal rendering of a plan tree for ``taskship review`` (REQ-TS-012)."""
from __future__ import annotations

from .model import Plan


def render_tree(plan: Plan) -> str:
    """Render the epic → story → task tree as indented text.

    @implements REQ-TS-012
    """
    lines = [f"{plan.product}  ({plan.jira_project})"]
    for epic in plan.epics:
        lines.append(f"  ▸ [Epic] {epic.title}")
        for story in epic.stories:
            kind = "  (devops)" if story.kind == "devops" else ""
            lines.append(f"    • [Story{kind}] {story.title}")
            for task in story.tasks:
                sub = f"/{task.subtype}" if task.subtype else ""
                lines.append(f"      - [{task.type}{sub}] {task.title}")
    return "\n".join(lines)
