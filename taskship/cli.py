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
