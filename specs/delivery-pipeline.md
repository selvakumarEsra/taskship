---
id: DELIVERY-DOC
title: TaskShip delivery orchestration & reporting
owner: "@selvakumar"
priority: medium
version: 1
---

<!-- id: DELIVERY-DOC -->
# TaskShip delivery orchestration & reporting

The planning core (plan-as-code, idempotent sync, reverse status) turns a brief
into a Jira board. This document adds the layer above it: **who does the work,
in which cadence, and how progress is reported** — assignment, a Scrum sprint
field, a solo-friendly Kanban view, a daily-standup ceremony, and an executive
status report.

The design preserves TaskShip's core split — **plan = intent, board = status**:

- **Declarative delivery state** (assignee, sprint) lives in `plan.yaml` and is
  synced idempotently through the existing reconciler, cascading
  `defaults → epic → story → task` exactly like labels. Editing it is the same
  reviewable plan-as-code workflow.
- **Ceremonies** (`board`, `standup`, `report`) are **read-only** with respect
  to `plan.yaml`. They pull live board state via reverse sync and render it;
  they MUST NOT rewrite authored intent.

Decisions of record for v1:

- **Assignee identity:** authored in `plan.yaml` as an email or a Jira
  `accountId`; TaskShip resolves an email to an `accountId` when writing to Jira.
  Encoded on the Jira issue's standard **assignee** field.
- **"Done" for rollups:** a node counts as done when its Jira status is in the
  **Done** status category. **"Blocked":** a node is blocked when its Jira status
  is in a configurable blocked set (default: any status whose name contains
  "block", case-insensitive) or the issue is flagged.
- **Kanban vs Scrum:** both are supported and independent — Kanban (`board`)
  needs no sprint; Scrum uses the `sprint` field. A solo dev can use `board` +
  `standup` + `report` with no sprints at all.
- **Ceremony output:** `standup` renders to the terminal and to a Markdown file;
  `report` renders to a self-contained HTML file for senior-management sharing.

<!-- id: REQ-DEL-001 -->
## Plan nodes MUST carry a cascading assignee that syncs to Jira

An epic, story, or task MUST be able to declare an `assignee`, which cascades
`defaults → epic → story → task` (a narrower scope overrides), and which the
idempotent sync writes to the Jira issue's assignee field. Assignment MUST be
idempotent: re-syncing an unchanged assignee makes no Jira call.

implementations:

## Acceptance
<!-- id: REQ-DEL-001.A1 -->
- A task with no `assignee` inherits its story's, which falls back to the epic's
  and then to `defaults`; a node that declares its own `assignee` overrides the inherited one.
<!-- id: REQ-DEL-001.A2 -->
- Syncing a node whose resolved `assignee` changed issues exactly one update that
  sets the Jira issue's assignee; re-syncing with the same assignee makes no call (skip).
<!-- id: REQ-DEL-001.A3 -->
- An `assignee` authored as an email is applied to the correct Jira user; an
  unresolvable assignee is reported as an error naming the node, and no other node's sync is aborted.
<!-- id: REQ-DEL-001.A4 -->
- `taskship assign <node-id> <assignee>` sets the assignee for that node in
  `plan.yaml` (reviewable), and a subsequent `sync` applies it to Jira.

<!-- id: REQ-DEL-002 -->
## Stories and tasks MUST carry a cascading sprint that syncs to Jira

A story or task MUST be able to declare a `sprint`, which cascades and overrides
like `assignee`, and which the sync writes to the Jira issue's sprint so the work
lands in the right Scrum iteration. Sprint assignment MUST be idempotent.

implementations:

## Acceptance
<!-- id: REQ-DEL-002.A1 -->
- A task with no `sprint` inherits its story's resolved `sprint`; a node that
  declares its own `sprint` overrides the inherited one.
<!-- id: REQ-DEL-002.A2 -->
- Syncing a node whose resolved `sprint` changed issues exactly one update
  placing the Jira issue in that sprint; re-syncing unchanged makes no call.
<!-- id: REQ-DEL-002.A3 -->
- A node with no `sprint` anywhere in its cascade is left out of any sprint (the
  sprint field is not written), so Kanban-only users are unaffected.

<!-- id: REQ-DEL-003 -->
## A Kanban board view MUST group work by live status column

TaskShip MUST provide a read-only `board` view that pulls live board state and
groups the plan's tasks into status columns (e.g. To Do / In Progress / Done),
so a solo developer can track flow without any sprint. It MUST NOT modify
`plan.yaml`.

implementations:

## Acceptance
<!-- id: REQ-DEL-003.A1 -->
- `taskship board` renders the plan's synced tasks grouped under their current
  Jira status as columns, each task showing its title and Jira key.
<!-- id: REQ-DEL-003.A2 -->
- A task not yet synced (no Jira key) appears under an "unsynced"/backlog grouping
  rather than being dropped from the view.
<!-- id: REQ-DEL-003.A3 -->
- Running `board` leaves `plan.yaml` unchanged on disk and requires no sprint to be set.

<!-- id: REQ-DEL-004 -->
## A standup command MUST diff board state since the last snapshot, per assignee

TaskShip MUST provide a `standup` ceremony that snapshots current board state and
reports what changed since the previous snapshot — grouped per assignee and
flagging blocked or conflicting items — so a team can run a daily standup from
it. It MUST be read-only with respect to `plan.yaml`.

implementations:

## Acceptance
<!-- id: REQ-DEL-004.A1 -->
- On first run `standup` records a board-state snapshot under `.taskship/`; on the
  next run it classifies each node as done-since-last / in-progress / not-started using the two snapshots.
<!-- id: REQ-DEL-004.A2 -->
- The standup output groups items by assignee and flags any item that is blocked
  or in an unresolved plan-vs-board conflict.
<!-- id: REQ-DEL-004.A3 -->
- `standup` renders to the terminal and writes the same content to a Markdown
  file that can be pasted into Slack/email; neither output modifies `plan.yaml`.

<!-- id: REQ-DEL-005 -->
## An executive status report MUST roll up progress, workload, and risks to HTML

TaskShip MUST provide a `report` command that produces a self-contained HTML
status report for senior management, rolling up per-epic completion, workload by
assignee, and delivery risks. It MUST be read-only with respect to `plan.yaml`.

implementations:

## Acceptance
<!-- id: REQ-DEL-005.A1 -->
- The report shows, per epic, a completion figure (done ÷ total leaf tasks) based
  on live Jira status, plus overall counts by status.
<!-- id: REQ-DEL-005.A2 -->
- The report shows a workload breakdown by assignee (count of items, and how many
  are done vs in progress).
<!-- id: REQ-DEL-005.A3 -->
- The report surfaces delivery risks — items that are blocked, plan-vs-board
  conflicts, and orphaned issues — in a dedicated section.
<!-- id: REQ-DEL-005.A4 -->
- The report is written as a single self-contained HTML file (styles inlined, no
  external asset fetch required to view it) and does not modify `plan.yaml`.
