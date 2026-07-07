"""Read-only delivery ceremonies: board, standup, report (REQ-DEL-003/004/005).

All three consume the reverse-sync :class:`~taskship.status.StatusRow` view and
never mutate ``plan.yaml``. "Done" and "blocked" are derived from the live Jira
status name using the document's decisions of record.
"""
from __future__ import annotations

import html
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

from .status import StatusRow

_DONE = {"done", "closed", "resolved", "complete", "completed"}
_BACKLOG = "Backlog"
_COLUMN_ORDER = ["Backlog", "To Do", "In Progress", "In Review", "Done"]


def is_done(status: Optional[str]) -> bool:
    if not status:
        return False
    s = status.strip().lower()
    return s in _DONE or "done" in s


def is_blocked(status: Optional[str]) -> bool:
    return bool(status) and "block" in status.lower()


# --- REQ-DEL-003: Kanban board ----------------------------------------------

def board_columns(rows: list[StatusRow]) -> "OrderedDict[str, list[StatusRow]]":
    """Group the plan's tasks into status columns; unsynced → Backlog.

    @implements REQ-DEL-003
    """
    cols: "OrderedDict[str, list[StatusRow]]" = OrderedDict()
    for name in _COLUMN_ORDER:
        cols[name] = []
    for row in rows:
        if row.kind != "task":
            continue
        column = _BACKLOG if (row.jira is None or not row.status) else row.status
        cols.setdefault(column, []).append(row)
    # Drop empty predefined columns except Backlog so the board stays tight.
    return OrderedDict((k, v) for k, v in cols.items() if v or k == _BACKLOG)


# --- REQ-DEL-004: standup ----------------------------------------------------

def standup_snapshot(rows: list[StatusRow]) -> dict[str, Optional[str]]:
    """A minimal board snapshot ({task id → status}) to diff against next run."""
    return {r.external_id: r.status for r in rows if r.kind == "task"}


@dataclass
class StandupItem:
    external_id: str
    title: str
    state: str          # "done_since" | "in_progress" | "not_started" | "done"
    jira: Optional[str]
    blocked: bool
    conflict: bool


def standup_diff(
    prev: dict[str, Optional[str]],
    rows: list[StatusRow],
    conflict_ids: Optional[set[str]] = None,
) -> "OrderedDict[str, list[StandupItem]]":
    """Classify each task vs the previous snapshot, grouped by assignee.

    @implements REQ-DEL-004
    """
    conflict_ids = conflict_ids or set()
    by_assignee: "OrderedDict[str, list[StandupItem]]" = OrderedDict()
    for row in rows:
        if row.kind != "task":
            continue
        done_now = is_done(row.status)
        was_done = is_done(prev.get(row.external_id))
        if done_now and not was_done:
            state = "done_since"
        elif done_now:
            state = "done"
        elif row.status:
            state = "in_progress"
        else:
            state = "not_started"
        item = StandupItem(
            external_id=row.external_id, title=row.title, state=state, jira=row.jira,
            blocked=is_blocked(row.status), conflict=row.external_id in conflict_ids,
        )
        by_assignee.setdefault(row.assignee or "Unassigned", []).append(item)
    return by_assignee


def render_standup_md(diff: "OrderedDict[str, list[StandupItem]]") -> str:
    """Render the standup as Markdown (terminal output uses the same text)."""
    icon = {"done_since": "✅", "done": "☑", "in_progress": "🔨", "not_started": "⬜"}
    lines = ["# Daily standup", ""]
    for assignee, items in diff.items():
        lines.append(f"## {assignee}")
        for it in sorted(items, key=lambda x: x.state):
            flags = ""
            if it.blocked:
                flags += " ⛔ blocked"
            if it.conflict:
                flags += " ⚠ conflict"
            key = f"[{it.jira}] " if it.jira else ""
            lines.append(f"- {icon.get(it.state, '·')} {key}{it.title}{flags}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# --- REQ-DEL-005: executive report -------------------------------------------

@dataclass
class EpicRollup:
    external_id: str
    title: str
    total: int
    done: int

    @property
    def pct(self) -> int:
        return round(100 * self.done / self.total) if self.total else 0


@dataclass
class ReportData:
    epics: list[EpicRollup]
    status_counts: "OrderedDict[str, int]"
    workload: dict[str, dict[str, int]]   # assignee → {total, done, in_progress}
    blocked: list[StatusRow]
    conflicts: list[dict]
    orphans: list[str]


def build_report(
    rows: list[StatusRow], conflicts: Optional[list[dict]] = None,
    orphans: Optional[list[str]] = None,
) -> ReportData:
    """Roll up completion, workload, and risks for the exec report.

    @implements REQ-DEL-005
    """
    tasks = [r for r in rows if r.kind == "task"]
    epics = [r for r in rows if r.kind == "epic"]

    epic_rollups = []
    for epic in epics:
        prefix = epic.external_id + "/"
        leaves = [t for t in tasks if t.external_id.startswith(prefix)]
        epic_rollups.append(EpicRollup(
            external_id=epic.external_id, title=epic.title,
            total=len(leaves), done=sum(1 for t in leaves if is_done(t.status)),
        ))

    status_counts: "OrderedDict[str, int]" = OrderedDict()
    for t in tasks:
        label = t.status or "Backlog"
        status_counts[label] = status_counts.get(label, 0) + 1

    workload: dict[str, dict[str, int]] = {}
    for t in tasks:
        who = t.assignee or "Unassigned"
        w = workload.setdefault(who, {"total": 0, "done": 0, "in_progress": 0})
        w["total"] += 1
        if is_done(t.status):
            w["done"] += 1
        elif t.status:
            w["in_progress"] += 1

    return ReportData(
        epics=epic_rollups,
        status_counts=status_counts,
        workload=workload,
        blocked=[t for t in tasks if is_blocked(t.status)],
        conflicts=conflicts or [],
        orphans=orphans or [],
    )


def render_report_html(data: ReportData, product: str) -> str:
    """Render the report as a single self-contained HTML document.

    @implements REQ-DEL-005
    """
    e = html.escape

    def bar(pct: int) -> str:
        return (f'<div class="bar"><span style="width:{pct}%"></span></div>'
                f'<span class="pct">{pct}%</span>')

    epic_rows = "".join(
        f"<tr><td>{e(ep.title)}</td><td>{ep.done}/{ep.total}</td>"
        f"<td class='barcell'>{bar(ep.pct)}</td></tr>"
        for ep in data.epics
    )
    status_rows = "".join(
        f"<tr><td>{e(k)}</td><td>{v}</td></tr>" for k, v in data.status_counts.items()
    )
    work_rows = "".join(
        f"<tr><td>{e(who)}</td><td>{w['total']}</td><td>{w['done']}</td>"
        f"<td>{w['in_progress']}</td></tr>"
        for who, w in sorted(data.workload.items())
    )
    risk_items = []
    for t in data.blocked:
        risk_items.append(f"<li class='r-block'>⛔ Blocked — {e(t.title)} "
                          f"({e(t.jira or '—')})</li>")
    for c in data.conflicts:
        risk_items.append(f"<li class='r-conf'>⚠ Conflict — {e(str(c.get('id')))} "
                          f"field {e(str(c.get('field')))}</li>")
    for o in data.orphans:
        risk_items.append(f"<li class='r-orph'>🗑 Orphaned — {e(o)}</li>")
    risks = "".join(risk_items) or "<li class='r-ok'>No risks detected.</li>"

    total_tasks = sum(w["total"] for w in data.workload.values())
    total_done = sum(w["done"] for w in data.workload.values())
    overall = round(100 * total_done / total_tasks) if total_tasks else 0

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(product)} — status report</title>
<style>
  :root {{ --brand:#5b5bef; --ink:#10131a; --muted:#5a6273; --border:#e6e8ee; --ok:#12996b; --warn:#b26a00; --bg:#f7f8fa; }}
  * {{ box-sizing:border-box; }}
  body {{ font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; color:var(--ink); margin:0; background:var(--bg); }}
  .wrap {{ max-width:860px; margin:0 auto; padding:40px 24px 64px; }}
  header {{ border-bottom:2px solid var(--brand); padding-bottom:16px; margin-bottom:8px; }}
  h1 {{ margin:0; font-size:1.7rem; }}
  .sub {{ color:var(--muted); margin-top:6px; }}
  .kpi {{ display:flex; gap:16px; margin:24px 0; flex-wrap:wrap; }}
  .kpi div {{ background:#fff; border:1px solid var(--border); border-radius:12px; padding:16px 20px; flex:1; min-width:140px; }}
  .kpi b {{ font-size:2rem; display:block; color:var(--brand); }}
  h2 {{ font-size:1.15rem; margin:32px 0 10px; }}
  table {{ width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--border); border-radius:12px; overflow:hidden; }}
  th,td {{ text-align:left; padding:10px 14px; border-bottom:1px solid var(--border); font-size:0.95rem; }}
  th {{ background:#eef0f6; color:var(--muted); font-weight:600; }}
  .barcell {{ display:flex; align-items:center; gap:10px; }}
  .bar {{ flex:1; height:9px; background:#edeff5; border-radius:6px; overflow:hidden; }}
  .bar span {{ display:block; height:100%; background:var(--brand); }}
  .pct {{ font-variant-numeric:tabular-nums; color:var(--muted); font-size:0.85rem; }}
  ul.risks {{ list-style:none; padding:0; margin:0; }}
  ul.risks li {{ background:#fff; border:1px solid var(--border); border-left:4px solid var(--warn); border-radius:8px; padding:10px 14px; margin-bottom:8px; }}
  .r-ok {{ border-left-color:var(--ok) !important; }}
  footer {{ margin-top:40px; color:var(--muted); font-size:0.82rem; }}
</style></head>
<body><div class="wrap">
  <header>
    <h1>{e(product)} — delivery status</h1>
    <div class="sub">Generated by TaskShip from live Jira board state · plan-vs-reality</div>
  </header>
  <div class="kpi">
    <div><b>{overall}%</b>overall complete</div>
    <div><b>{total_done}/{total_tasks}</b>tasks done</div>
    <div><b>{len(data.blocked) + len(data.conflicts) + len(data.orphans)}</b>open risks</div>
  </div>
  <h2>Progress by epic</h2>
  <table><thead><tr><th>Epic</th><th>Done</th><th>Completion</th></tr></thead><tbody>{epic_rows}</tbody></table>
  <h2>Workload by assignee</h2>
  <table><thead><tr><th>Assignee</th><th>Total</th><th>Done</th><th>In progress</th></tr></thead><tbody>{work_rows}</tbody></table>
  <h2>Status breakdown</h2>
  <table><thead><tr><th>Status</th><th>Tasks</th></tr></thead><tbody>{status_rows}</tbody></table>
  <h2>Delivery risks</h2>
  <ul class="risks">{risks}</ul>
  <footer>TaskShip · Jira is the system of record, TaskShip is the system of intent.</footer>
</div></body></html>
"""
