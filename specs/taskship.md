---
id: TASKSHIP-DOC
title: TaskShip — plan-as-code planning layer over Jira
owner: "@selvakumar"
priority: high
version: 1
---

<!-- id: TASKSHIP-DOC -->
# TaskShip

TaskShip is the system of *intent* that sits above Jira, the system of *record*. A
user describes a product; TaskShip decomposes it into a structured Epic → Story →
Task tree, emits it as a version-controlled `plan.yaml` that can be reviewed in a
pull request, then reconciles it into Jira Cloud **idempotently** — re-running never
duplicates, it diffs and patches only what changed. The same core engine is driven
two ways: a CLI for humans and an MCP server for agents.

The two load-bearing properties are **plan-as-code** (planning is reviewable,
diffable, regenerable) and **idempotent sync** (safe to run repeatedly, so an agent
can plan → push → replan without corrupting the board).

Scope of this document is the v0 MVP contract. v0 decisions of record:

- **Implementation language & core libraries:** Python 3.11+. pydantic v2 (plan
  schema + validation), ruamel.yaml (comment-preserving YAML round-trip), httpx
  (Jira REST client), click (CLI), the `mcp` Python SDK (server), pytest (tests).
  Packaged as an importable `taskship` package (`taskship/model.py`,
  `taskship/plan_io.py`, `taskship/reconcile.py`, `taskship/jira.py`,
  `taskship/cli.py`, `taskship/mcp_server.py`; `templates/` for typed templates).
- **Jira project type:** company-managed.
- **Task typing in Jira:** encoded as labels (`taskship:type:<type>`,
  `taskship:subtype:<subtype>`) — no custom-field or issue-type admin setup required.
- **External-id watermark:** a `taskship:<local-id>` label on every issue.
- **Auth:** Jira Cloud API token + account email (HTTP Basic) for a single tool
  account. OAuth 3LO is out of scope for v0.
- **Conflict policy:** on divergence between plan and board, TaskShip surfaces the
  conflict for a human — it MUST NOT silently overwrite hand edits.
- **Deletions:** never automatic — a removed node is flagged, not deleted.

Domain model (mirrors Jira's issue-type hierarchy 1:1): a product contains Epics
(Jira level 1); each Epic contains Stories (level 0), including DevOps stories
flagged `kind: devops`; each Story contains Tasks (level 0) typed `biz-spec` /
`tech-spec` / `devops` / `qa` / `docs`, tech-spec optionally subtyped
`perf` / `optimization` / `security` / `scalability`. Parent linkage uses Jira's
standard `parent` field, never the deprecated Epic Link field.

<!-- id: REQ-TS-001 -->
## The plan MUST round-trip through a validated YAML file

The plan is a single version-controlled `plan.yaml` describing
product → epics → stories → tasks. TaskShip MUST parse it into a validated in-memory
model and serialize it back without losing authored content, so the file is safe to
review and diff in version control. An invalid plan MUST be rejected with a
structured error, never silently repaired.

implementations:

## Acceptance
<!-- id: REQ-TS-001.A1 -->
- Loading a well-formed `plan.yaml` and re-serializing it produces a file whose
  authored fields and comments are preserved (round-trip is lossless for author-visible content).
<!-- id: REQ-TS-001.A2 -->
- A plan whose node is missing a required field (e.g. an epic with no `title`, or a
  `product`/`jira_project` absent at the top level) is rejected with an error naming
  the offending node path; no partial write occurs.
<!-- id: REQ-TS-001.A3 -->
- A `tech-spec` task with `subtype: perf` that omits `metrics` (baseline + target) is
  rejected at validation time with an error naming the task.

<!-- id: REQ-TS-002 -->
## Every node MUST have a stable local identity independent of its Jira key

Each epic, story, and task MUST carry a local `id` — supplied by the author or
deterministically slugged from its title — that never changes across regenerations.
This local id, not the Jira key, is the identity TaskShip tracks. Renaming a node's
`title` MUST NOT change its identity or cause a duplicate on the next sync.

implementations:

## Acceptance
<!-- id: REQ-TS-002.A1 -->
- Two nodes with the same title under different parents resolve to distinct,
  fully-qualified local ids (e.g. `guest-flow/biz-spec-1`), so titles need not be globally unique.
<!-- id: REQ-TS-002.A2 -->
- Changing a node's `title` while keeping its `id` leaves its identity unchanged: a
  subsequent sync updates the existing Jira issue rather than creating a new one.
<!-- id: REQ-TS-002.A3 -->
- A node authored without an explicit `id` receives a deterministic slug that is
  identical on every load of the same file (stable, not random).

<!-- id: REQ-TS-003 -->
## Fields MUST cascade from defaults to epic to story to task

Fields defined at a broader scope MUST be inherited by narrower scopes, and a
narrower scope MUST be able to override them. The cascade order is
`defaults → epic → story → task`. This keeps the plan concise while letting any node
opt out.

implementations:

## Acceptance
<!-- id: REQ-TS-003.A1 -->
- A task with no `labels` of its own resolves to its story's labels, which in turn
  fall back to `defaults.labels` when the story defines none.
<!-- id: REQ-TS-003.A2 -->
- A task that declares its own `labels` uses exactly those and does not merge in the
  inherited set (override, not union), unless the author opts into merge explicitly.
<!-- id: REQ-TS-003.A3 -->
- The resolved (post-cascade) field set for any node is inspectable, so a reviewer
  can see what a task will actually carry into Jira.

<!-- id: REQ-TS-004 -->
## Task-type templates MUST render structured ADF and MUST refuse incomplete specs

Each task `type` has a versioned template that renders its required fields into the
Jira issue description as Atlassian Document Format (ADF) and sets its labels.
Templates MUST enforce completeness: a template whose required fields are unmet MUST
refuse to render rather than emit a blank or partial ticket. Templates MUST be
versioned files a team can fork without editing TaskShip's core.

implementations:

## Acceptance
<!-- id: REQ-TS-004.A1 -->
- The `biz-spec` template renders an ADF description containing the problem
  statement, user story, acceptance criteria, out-of-scope, and open questions sections.
<!-- id: REQ-TS-004.A2 -->
- The `tech-spec` template with `subtype: perf` refuses to render when no measurable
  baseline+target metric is present, and renders the metric (e.g. `p95 480ms → 200ms`) when present.
<!-- id: REQ-TS-004.A3 -->
- The `devops` template renders infra changes, pipeline stages, rollback plan, and a
  runbook link section.
<!-- id: REQ-TS-004.A4 -->
- Rendered output is valid ADF accepted by the Jira create/update description field
  (round-trips through the REST API without a 400).
<!-- id: REQ-TS-004.A5 -->
- A team can point TaskShip at a forked template directory and its templates render
  in place of the built-ins, with no change to TaskShip's source.

<!-- id: REQ-TS-005 -->
## Sync MUST be idempotent — create, update, or skip per node

For each node, in an order where every parent is processed before its children,
TaskShip MUST decide exactly one of: create (no existing Jira issue), update (issue
exists but the node's content hash changed — patching only changed fields), or skip
(hash unchanged — no API call). Re-running an unchanged plan MUST produce zero
create/update calls. Parent linkage MUST use Jira's `parent` field.

implementations:

## Acceptance
<!-- id: REQ-TS-005.A1 -->
- Syncing a plan for the first time creates one Jira issue per node and records each
  node's Jira key and content hash in `.taskship/state.json`.
<!-- id: REQ-TS-005.A2 -->
- Immediately re-syncing the same unchanged plan issues zero create and zero update
  calls (every node resolves to skip).
<!-- id: REQ-TS-005.A3 -->
- Editing exactly one task's title and re-syncing issues exactly one update call,
  targeting only the changed fields of that one issue; all other nodes skip.
<!-- id: REQ-TS-005.A4 -->
- A story is created with its epic set as `parent`, and a task with its story (or
  epic) as `parent`; a child is never created before its parent exists.

<!-- id: REQ-TS-006 -->
## Sync MUST recover the id→key mapping when local state is missing

When `.taskship/state.json` is absent or does not contain a node (fresh checkout,
lost state), TaskShip MUST attempt to recover the mapping from Jira before deciding
to create, by searching for the node's `taskship:<local-id>` watermark label. Only if
no watermark match exists may it create a new issue. This prevents duplicate issues
after state loss.

implementations:

## Acceptance
<!-- id: REQ-TS-006.A1 -->
- With `state.json` deleted but issues still bearing `taskship:<id>` labels, a sync
  recovers each node's Jira key via label search and issues zero creates.
<!-- id: REQ-TS-006.A2 -->
- A node whose watermark label matches no Jira issue is created (fresh), and its new
  key + hash are written back to `state.json`.
<!-- id: REQ-TS-006.A3 -->
- Every issue TaskShip creates carries the `taskship:<local-id>` watermark label so
  future recovery is possible.

<!-- id: REQ-TS-007 -->
## Sync MUST support a dry-run that performs no writes

A `--dry-run` sync MUST compute and report the full create/update/skip plan without
issuing any mutating Jira call. This lets a human or agent preview the effect of a
sync before committing to it.

implementations:

## Acceptance
<!-- id: REQ-TS-007.A1 -->
- `sync --dry-run` prints, per node, one of create / update / skip and the reason,
  and makes zero POST/PUT calls to Jira.
<!-- id: REQ-TS-007.A2 -->
- A dry-run leaves `.taskship/state.json` byte-for-byte unchanged.

<!-- id: REQ-TS-008 -->
## Removing a node MUST NOT delete its Jira issue automatically

When a node present in `state.json` no longer appears in `plan.yaml`, TaskShip MUST
NOT delete or close the Jira issue. It MUST instead flag the issue with a
`taskship:orphaned` label and report it, leaving resolution to a human.

implementations:

## Acceptance
<!-- id: REQ-TS-008.A1 -->
- Removing a node from `plan.yaml` and syncing applies the `taskship:orphaned` label
  to its Jira issue and issues no delete/transition-to-done call.
<!-- id: REQ-TS-008.A2 -->
- The orphaned node is reported in the sync summary so the human can act on it.

<!-- id: REQ-TS-009 -->
## Jira REST calls MUST be rate-limit-aware and retried with backoff

TaskShip MUST tolerate Jira Cloud rate limiting: on a throttled or transient failure
response it MUST retry with backoff up to a bounded number of attempts rather than
aborting the whole sync, and MUST surface a clear error if the ceiling is exceeded.

implementations:

## Acceptance
<!-- id: REQ-TS-009.A1 -->
- A 429 response with a `Retry-After` header causes the client to wait and retry, and
  the sync ultimately succeeds without operator intervention.
<!-- id: REQ-TS-009.A2 -->
- Retries are bounded; after the attempt ceiling is hit the call fails with an error
  identifying the node and the underlying Jira status, and the sync stops cleanly.

<!-- id: REQ-TS-010 -->
## Reverse sync MUST pull live board state without overwriting intent

TaskShip MUST be able to read current issue state back from Jira — status, assignee,
story points — and present a plan-vs-reality view. Reverse sync MUST be read-only
with respect to `plan.yaml`: it annotates, it MUST NOT rewrite authored intent.

implementations:

## Acceptance
<!-- id: REQ-TS-010.A1 -->
- `status` fetches each mapped issue's current status, assignee, and story points and
  displays them alongside the planned node.
<!-- id: REQ-TS-010.A2 -->
- Running reverse sync leaves `plan.yaml`'s authored fields unchanged on disk.

<!-- id: REQ-TS-011 -->
## Divergence between plan and board MUST be surfaced, not silently overwritten

When a field TaskShip manages has been changed by hand in Jira such that the board
value no longer matches the plan-derived value, sync MUST detect and report the
divergence for the human rather than blindly overwriting it. (v0 conflict policy:
surface for human.)

implementations:

## Acceptance
<!-- id: REQ-TS-011.A1 -->
- A hand edit in Jira to a TaskShip-managed field, followed by a sync where the plan
  also changed that node, is reported as a conflict listing the field, the plan value, and the board value.
<!-- id: REQ-TS-011.A2 -->
- The conflicting field is not overwritten by that sync; the human decides the resolution.

<!-- id: REQ-TS-012 -->
## A CLI MUST expose init, review, sync, and status over the core engine

Humans MUST be able to drive the full v0 loop from a CLI: scaffold a project,
render the plan tree, sync idempotently, and view board status. The CLI MUST be a
thin wrapper over the core library so its behavior is identical to the MCP path.

implementations:

## Acceptance
<!-- id: REQ-TS-012.A1 -->
- `taskship init` scaffolds `plan.yaml`, the templates directory, and `.taskship/`.
<!-- id: REQ-TS-012.A2 -->
- `taskship review` renders the epic → story → task tree in the terminal from the
  current `plan.yaml`.
<!-- id: REQ-TS-012.A3 -->
- `taskship sync` (and `taskship sync --dry-run`) invoke the same reconcile engine and
  produce the same create/update/skip decisions as the MCP `sync_to_jira` tool for the same plan.
<!-- id: REQ-TS-012.A4 -->
- `taskship status` renders the plan-vs-reality view from reverse sync.

<!-- id: REQ-TS-013 -->
## An MCP server MUST expose the same operations as agent tools

Agents MUST be able to drive the identical engine through MCP tools:
`decompose_brief`, `get_plan` / `update_plan`, `add_epic` / `add_story` / `add_task`,
`sync_to_jira`, and `get_board_status`. The MCP layer MUST read and mutate the same
plan-as-code a human edits, so an agent's changes are reviewable in the same file.

implementations:

## Acceptance
<!-- id: REQ-TS-013.A1 -->
- `sync_to_jira(dry_run=true)` returns the same create/update/skip diff the CLI
  `sync --dry-run` produces for the same plan, and writes nothing.
<!-- id: REQ-TS-013.A2 -->
- `add_task` mutates the in-memory plan such that a subsequent `get_plan` reflects the
  new task and a serialize produces a `plan.yaml` a human can review.
<!-- id: REQ-TS-013.A3 -->
- `get_board_status` returns live issue state equivalent to the CLI `status` view.

<!-- id: REQ-TS-014 -->
## Decomposition MUST emit only schema-valid plans

`taskship plan "<brief>"` and the `decompose_brief` tool MUST produce plan output
that validates against the plan schema before it is written; an invalid generated
plan MUST be rejected, never silently patched into shape. Decomposition MUST NOT
write to Jira — it returns the tree only.

implementations:

## Acceptance
<!-- id: REQ-TS-014.A1 -->
- A generated plan that fails schema validation is rejected with a validation error;
  no `plan.yaml` is written from invalid output.
<!-- id: REQ-TS-014.A2 -->
- `decompose_brief(text)` returns the structured tree and makes zero Jira calls.
<!-- id: REQ-TS-014.A3 -->
- A successfully decomposed brief yields a plan that, when synced, passes the same
  validation and reconcile path as a hand-authored plan (decomposition is a bolt-on, not a special case).
