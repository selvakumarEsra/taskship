"""TaskShip CLI — a thin click wrapper over the core engine (REQ-TS-012).

Every command drives the same library the MCP server does, so behaviour is
identical whichever front door is used: ``init`` scaffolds, ``review`` renders
the plan tree, ``sync`` reconciles idempotently (``--dry-run`` previews), and
``status`` shows the plan-vs-reality view via reverse sync.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import click

from .connect import OfflineClient, build_client
from .plan_io import load_plan
from .reconcile import reconcile
from .render import render_tree
from .scaffold import init_project
from .state import StateStore
from .status import build_status_view


def _templates_dir(root: Path) -> Optional[Path]:
    d = root / "templates"
    return d if d.is_dir() else None


def _load_plan_or_die(root: Path):
    plan_path = root / "plan.yaml"
    if not plan_path.exists():
        raise click.ClickException(
            f"no plan.yaml in {root} — run `taskship init` first"
        )
    plan, _raw = load_plan(plan_path)
    return plan


def _build_client(cfg: dict):
    """Construct a real Jira client; a seam the CLI tests override."""
    from .connect import MissingCredentials
    try:
        return build_client(cfg["project"])
    except MissingCredentials as exc:
        raise click.ClickException(str(exc))


def _config(plan) -> dict:
    return {"project": plan.jira_project}


@click.group()
@click.option("--dir", "root", default=".", type=click.Path(file_okay=False),
              help="Project directory (contains plan.yaml).")
@click.pass_context
def cli(ctx: click.Context, root: str) -> None:
    ctx.obj = {"root": Path(root)}


@cli.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """Scaffold plan.yaml, templates/, and .taskship/."""
    paths = init_project(ctx.obj["root"])
    click.echo(f"Scaffolded plan.yaml, templates/, .taskship/ in {ctx.obj['root']}")
    click.echo(f"  edit {paths['plan']} then `taskship review`")


@cli.command()
@click.argument("brief")
@click.option("--force", is_flag=True, help="Overwrite an existing plan.yaml.")
@click.pass_context
def plan(ctx: click.Context, brief: str, force: bool) -> None:
    """Decompose a product brief into plan.yaml (schema-validated)."""
    from .decompose import decompose_brief
    from ruamel.yaml import YAML

    root = ctx.obj["root"]
    plan_path = root / "plan.yaml"
    if plan_path.exists() and not force:
        raise click.ClickException(f"{plan_path} exists — pass --force to overwrite")

    tree = decompose_brief(brief)  # raises on invalid output; no write on failure
    root.mkdir(parents=True, exist_ok=True)
    yaml = YAML()
    yaml.indent(mapping=2, sequence=4, offset=2)
    with plan_path.open("w", encoding="utf-8") as fh:
        yaml.dump(tree, fh)
    click.echo(f"Wrote {plan_path} — review it, then `taskship sync --dry-run`")


@cli.command()
@click.pass_context
def review(ctx: click.Context) -> None:
    """Render the epic → story → task tree."""
    plan = _load_plan_or_die(ctx.obj["root"])
    click.echo(render_tree(plan))


@cli.command()
@click.argument("node_id")
@click.argument("assignee")
@click.pass_context
def assign(ctx: click.Context, node_id: str, assignee: str) -> None:
    """Set a node's assignee in plan.yaml (reviewable), e.g. `assign e/s/t alice@acme.com`."""
    from .plan_io import load_plan, dump_plan
    from .model import Plan
    from .identity import slug

    root = ctx.obj["root"]
    plan_path = root / "plan.yaml"
    if not plan_path.exists():
        raise click.ClickException(f"no plan.yaml in {root}")
    _plan, raw = load_plan(plan_path)

    def node_local_id(node) -> str:
        return node.get("id") or slug(node.get("title", ""))

    segments = node_id.split("/")
    level = {0: raw.get("epics", []), 1: "stories", 2: "tasks"}
    cursor_list = raw.get("epics", [])
    target = None
    for depth, seg in enumerate(segments):
        target = next((n for n in cursor_list if node_local_id(n) == seg), None)
        if target is None:
            raise click.ClickException(f"no node '{node_id}' (missing segment '{seg}')")
        if depth < len(segments) - 1:
            cursor_list = target.get(level[depth + 1], [])

    target["assignee"] = assignee
    Plan.from_mapping(raw)  # validate before writing
    dump_plan(raw, plan_path)
    click.echo(f"Assigned {node_id} → {assignee} in {plan_path}")


@cli.command()
@click.argument("title")
@click.option("--impact", help="Who/what is affected (definition-of-ready).")
@click.option("--evidence", help="Logs, links, or metrics.")
@click.option("--action", help="A suggested first action.")
@click.pass_context
def observe(ctx: click.Context, title: str, impact: Optional[str],
            evidence: Optional[str], action: Optional[str]) -> None:
    """Append a production observation to the ops intake lane (plan-only).

    @implements REQ-DOORS-002
    """
    from .session import TaskShipSession

    root = ctx.obj["root"]
    if not (root / "plan.yaml").exists():
        raise click.ClickException(f"no plan.yaml in {root} — run `taskship init` first")
    session = TaskShipSession(root)
    result = session.observe(title, impact=impact, evidence=evidence, action=action)
    session.save()
    if result["lane_created"]:
        click.echo("Created the ops-intake lane.")
    click.echo(f"Recorded observation {result['id']} — reaches Jira on the next `sync`.")


@cli.command()
@click.pass_context
def testplan(ctx: click.Context) -> None:
    """Derive one e2e test-case task per non-ops story (idempotent, plan-only).

    @implements REQ-DOORS-005
    """
    from .session import TaskShipSession

    root = ctx.obj["root"]
    if not (root / "plan.yaml").exists():
        raise click.ClickException(f"no plan.yaml in {root} — run `taskship init` first")
    session = TaskShipSession(root)
    result = session.derive_testplan()
    session.save()
    click.echo(
        f"testplan: added {len(result['added'])}, "
        f"skipped {len(result['skipped'])} existing test-case task(s)."
    )
    for qid in result["added"]:
        click.echo(f"  + {qid}")


@cli.command(name="raise")
@click.argument("title")
@click.option("--story", "story", help="Story id the defect was found against.")
@click.option("--epic", "epic", help="Epic id (parks in its <epic-id>-uat story).")
@click.option("--expected", help="Expected behaviour (definition-of-ready).")
@click.option("--actual", help="Actual behaviour observed.")
@click.option("--steps", help="Steps to reproduce.")
@click.option("--severity", help="How badly it blocks acceptance.")
@click.option("--environment", help="Build, browser, or data set.")
@click.option("--test", help="Failed regression test-case id (adds a test label).")
@click.pass_context
def raise_issue(ctx: click.Context, title: str, story: Optional[str],
                epic: Optional[str], expected: Optional[str],
                actual: Optional[str], steps: Optional[str],
                severity: Optional[str], environment: Optional[str],
                test: Optional[str]) -> None:
    """Park a UAT issue under the story it was found against (plan-only).

    @implements REQ-DOORS-008
    """
    from .session import PlanEditError, TaskShipSession

    root = ctx.obj["root"]
    if not (root / "plan.yaml").exists():
        raise click.ClickException(f"no plan.yaml in {root} — run `taskship init` first")
    session = TaskShipSession(root)
    try:
        result = session.raise_issue(
            title, story=story, epic=epic, expected=expected, actual=actual,
            steps=steps, severity=severity, environment=environment, test=test,
        )
    except PlanEditError as exc:
        raise click.ClickException(str(exc))
    session.save()
    if result["story_created"]:
        click.echo(f"Created the UAT fallback story {result['story']}.")
    click.echo(
        f"Raised UAT issue {result['id']} under {result['story']} — "
        "reaches Jira on the next `sync`."
    )


@cli.command()
@click.option("--dry-run", is_flag=True, help="Preview create/update/skip; no writes.")
@click.pass_context
def sync(ctx: click.Context, dry_run: bool) -> None:
    """Reconcile the plan into Jira idempotently."""
    root = ctx.obj["root"]
    plan = _load_plan_or_die(root)
    state = StateStore(root / ".taskship" / "state.json")
    client = OfflineClient() if dry_run else _build_client(_config(plan))

    report = reconcile(plan, client, state, dry_run=dry_run,
                       templates_dir=_templates_dir(root))

    header = "DRY RUN — no changes written\n" if dry_run else ""
    click.echo(header + _format_report(report))


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show the plan vs. live board state (reverse sync)."""
    root = ctx.obj["root"]
    plan = _load_plan_or_die(root)
    state = StateStore(root / ".taskship" / "state.json")
    client = _build_client(_config(plan))

    rows = build_status_view(plan, client, state)
    for row in rows:
        indent = {1: "  ", 0: "    "}.get(row.level, "      ")
        jira = row.jira or "—"
        live = row.status or "not synced"
        who = f" · {row.assignee}" if row.assignee else ""
        pts = f" · {row.story_points}pt" if row.story_points is not None else ""
        click.echo(f"{indent}{jira:<10} {live}{who}{pts}  {row.title}")


@cli.command()
@click.pass_context
def board(ctx: click.Context) -> None:
    """Kanban view: tasks grouped by live Jira status (no sprint needed)."""
    from .ceremonies import board_columns, triage_observations
    root = ctx.obj["root"]
    plan = _load_plan_or_die(root)
    state = StateStore(root / ".taskship" / "state.json")
    rows = build_status_view(plan, _build_client(_config(plan)), state)

    triage = triage_observations(rows)
    if triage:
        click.echo(f"\n  TRIAGE — observations awaiting prioritization  ({len(triage)})")
        for it in triage:
            key = f"{it.jira} " if it.jira else ""
            click.echo(f"    · {key}{it.title}")

    for column, items in board_columns(rows).items():
        click.echo(f"\n  {column.upper()}  ({len(items)})")
        for it in items:
            key = f"{it.jira} " if it.jira else ""
            who = f"  · {it.assignee}" if it.assignee else ""
            click.echo(f"    · {key}{it.title}{who}")


@cli.command()
@click.option("--out", default="standup.md", help="Markdown output file.")
@click.pass_context
def standup(ctx: click.Context, out: str) -> None:
    """Daily standup: what changed since the last run, per assignee."""
    import json
    from .ceremonies import standup_snapshot, standup_diff, render_standup_md
    root = ctx.obj["root"]
    plan = _load_plan_or_die(root)
    state = StateStore(root / ".taskship" / "state.json")
    client = _build_client(_config(plan))

    rows = build_status_view(plan, client, state)
    dry = reconcile(plan, client, state, dry_run=True, templates_dir=_templates_dir(root))
    conflict_ids = {c.external_id for c in dry.conflicts}

    snap_path = root / ".taskship" / "standup.json"
    prev = json.loads(snap_path.read_text()) if snap_path.exists() else {}
    diff = standup_diff(prev, rows, conflict_ids)

    md = render_standup_md(diff)
    click.echo(md)
    (root / out).write_text(md, encoding="utf-8")
    snap_path.parent.mkdir(parents=True, exist_ok=True)
    snap_path.write_text(json.dumps(standup_snapshot(rows), indent=2), encoding="utf-8")
    click.echo(f"— written to {root / out}")


@cli.command()
@click.option("--out", default="status-report.html", help="HTML output file.")
@click.pass_context
def report(ctx: click.Context, out: str) -> None:
    """Executive status report (HTML): progress, workload, risks."""
    from .ceremonies import build_report, render_report_html
    root = ctx.obj["root"]
    plan = _load_plan_or_die(root)
    state = StateStore(root / ".taskship" / "state.json")
    client = _build_client(_config(plan))

    rows = build_status_view(plan, client, state)
    dry = reconcile(plan, client, state, dry_run=True, templates_dir=_templates_dir(root))
    conflicts = [{"id": c.external_id, "field": c.field} for c in dry.conflicts]
    data = build_report(rows, conflicts=conflicts, orphans=dry.orphaned)

    (root / out).write_text(render_report_html(data, plan.product), encoding="utf-8")
    click.echo(f"Wrote status report → {root / out}")


def _format_report(report) -> str:
    lines = [f"{d.action:>6}  {d.external_id}   ({d.reason})" for d in report.decisions]
    if report.conflicts:
        lines.append("")
        lines.append("CONFLICTS (not overwritten — resolve by hand):")
        for c in report.conflicts:
            lines.append(
                f"  ! {c.external_id}.{c.field}: plan={c.plan_value!r} "
                f"board={c.board_value!r}"
            )
    if report.errors:
        lines.append("")
        lines.append("ERRORS (node skipped, sync continued):")
        for e in report.errors:
            lines.append(f"  ✗ {e.external_id}: {e.message}")
    summary = (
        f"created {len(report.created)} · updated {len(report.updated)} · "
        f"skipped {len(report.skipped)} · orphaned {len(report.orphaned)} · "
        f"conflicts {len(report.conflicts)} · errors {len(report.errors)}"
    )
    return "\n".join(lines + ["", summary])


if __name__ == "__main__":  # pragma: no cover
    cli()
