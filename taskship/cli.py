"""TaskShip CLI — a thin click wrapper over the core engine (REQ-TS-012).

Every command drives the same library the MCP server does, so behaviour is
identical whichever front door is used: ``init`` scaffolds, ``review`` renders
the plan tree, ``sync`` reconciles idempotently (``--dry-run`` previews), and
``status`` shows the plan-vs-reality view via reverse sync.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import click

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
    """Construct a real Jira client from config; overridden in tests."""
    from .jira import JiraClient
    missing = [k for k in ("base_url", "email", "token") if not cfg.get(k)]
    if missing:
        raise click.ClickException(
            "missing Jira credentials: set "
            + ", ".join(f"JIRA_{k.upper()}" for k in missing)
        )
    return JiraClient(cfg["base_url"], cfg["email"], cfg["token"], cfg["project"])


def _config(plan) -> dict:
    return {
        "base_url": os.environ.get("JIRA_BASE_URL"),
        "email": os.environ.get("JIRA_EMAIL"),
        "token": os.environ.get("JIRA_TOKEN"),
        "project": plan.jira_project,
    }


class _OfflineClient:
    """Read-only stand-in for a dry-run: knows of no existing issues."""

    def search_by_external_id(self, external_id: str) -> Optional[str]:
        return None


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
@click.pass_context
def review(ctx: click.Context) -> None:
    """Render the epic → story → task tree."""
    plan = _load_plan_or_die(ctx.obj["root"])
    click.echo(render_tree(plan))


@cli.command()
@click.option("--dry-run", is_flag=True, help="Preview create/update/skip; no writes.")
@click.pass_context
def sync(ctx: click.Context, dry_run: bool) -> None:
    """Reconcile the plan into Jira idempotently."""
    root = ctx.obj["root"]
    plan = _load_plan_or_die(root)
    state = StateStore(root / ".taskship" / "state.json")
    client = _OfflineClient() if dry_run else _build_client(_config(plan))

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
    summary = (
        f"created {len(report.created)} · updated {len(report.updated)} · "
        f"skipped {len(report.skipped)} · orphaned {len(report.orphaned)} · "
        f"conflicts {len(report.conflicts)}"
    )
    return "\n".join(lines + ["", summary])


if __name__ == "__main__":  # pragma: no cover
    cli()
