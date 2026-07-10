"""Project scaffolding for ``taskship init`` (REQ-TS-012).

Creates a reviewable starting point: a sample ``plan.yaml``, a ``templates/``
directory seeded with the built-in task templates (so a team can fork them in
place), and the ``.taskship/`` state directory.
"""
from __future__ import annotations

import shutil
from pathlib import Path

_BUILTIN_DIR = Path(__file__).parent / "builtin_templates"

SAMPLE_PLAN = """\
product: My Product
jira_project: PROJ            # your Jira project key

defaults:
  labels: [taskship]

epics:
  - id: first-epic
    title: First epic
    summary: What this epic delivers.
    stories:
      - id: first-story
        title: First user-facing capability
        labels: [frontend]
        tasks:
          - type: biz-spec
            title: Define requirements
          - type: tech-spec
            subtype: perf
            title: Meet the latency budget
            metrics: { baseline: "480ms", target: "200ms" }
      - id: delivery-pipeline
        title: Service delivery pipeline
        kind: devops           # DevOps as its own story
        tasks:
          - type: devops
            title: CI/CD + canary deploy
"""


def init_project(root: str | Path) -> dict[str, Path]:
    """Scaffold plan.yaml, templates/, and .taskship/ under ``root``.

    @implements REQ-TS-012

    Idempotent: existing files are left untouched (never overwritten).
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)

    state_dir = root / ".taskship"
    state_dir.mkdir(exist_ok=True)
    # state.json is meant to be committed (conflict detection needs its hashes
    # on every checkout); ceremony caches are machine-local.
    gitignore = state_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("standup.json\n", encoding="utf-8")

    templates_dir = root / "templates"
    templates_dir.mkdir(exist_ok=True)
    for src in sorted(_BUILTIN_DIR.glob("*.yaml")):
        dest = templates_dir / src.name
        if not dest.exists():
            shutil.copyfile(src, dest)

    plan_path = root / "plan.yaml"
    if not plan_path.exists():
        plan_path.write_text(SAMPLE_PLAN, encoding="utf-8")

    return {"plan": plan_path, "templates": templates_dir, "state_dir": state_dir}
