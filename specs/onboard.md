---
id: ONBOARD-DOC
title: Onboard an existing Jira project by key
owner: "@selvakumar"
priority: high
version: 1
---

<!-- id: ONBOARD-DOC -->
# Onboard an existing Jira project by key

`taskship onboard <JIRA-KEY>` is the front door for teams whose project
already lives in Jira: read every epic, story, and task in the project, build
the plan-as-code structure from them, adopt the existing issue keys into sync
state so the first sync updates rather than duplicates, and print a summary
for the human review that follows (VISION-DOC decision 1: one-time bootstrap,
plan-canonical thereafter).

Design decisions: onboarding is CLI-only (it needs `JIRA_*` credentials and is
a one-time setup act — MCP parity is a non-goal here, permitted by
REQ-VISION-001.A3's "where its inputs allow"); imported tasks whose type
TaskShip cannot infer get the new pass-through type `imported`, whose contract
is that **sync never rewrites their Jira description** — adopting a project
must not flatten or clobber descriptions the team wrote by hand; the knowledge
seeding and the interactive review dashboard are separate capabilities
(separate specs) — onboard's review surface is the draft `plan.yaml` itself
plus the printed summary.

Non-goals: no import of comments, attachments, worklogs, or sub-tasks below
the task level; no continuous re-import (VISION-DOC decision 1); no automatic
pruning — deciding what to keep is the human review's job.

<!-- id: REQ-ONBOARD-001 -->
## `taskship onboard <KEY>` MUST build a draft plan from the live project

The command reads the project's epic → story → task hierarchy from Jira and
writes it as a schema-valid `plan.yaml`.

implementations:
  - taskship/onboard.py
  - taskship/cli.py:onboard

## Acceptance
<!-- id: REQ-ONBOARD-001.A1 -->
- `taskship onboard <KEY>` fetches all non-done epics, stories, and tasks in
  project `<KEY>` (paginating past Jira's page-size limits) and writes a
  `plan.yaml` whose tree mirrors the Jira parent hierarchy, with
  `jira_project: <KEY>` set.
<!-- id: REQ-ONBOARD-001.A2 -->
- Every imported node gets a pinned `id` derived from its Jira key (e.g.
  `PROJ-123` → an id embedding the key), so later retitles in the plan never
  change identity.
<!-- id: REQ-ONBOARD-001.A3 -->
- Issues that fit no lane (orphaned tasks with no epic, unrecognized issue
  types) are not silently dropped: they land under a clearly-named catch-all
  epic or are listed in the summary as skipped, with counts.
<!-- id: REQ-ONBOARD-001.A4 -->
- The resulting `plan.yaml` validates against the plan schema; a project
  whose content cannot produce a valid plan fails with a named error and
  writes nothing.

<!-- id: REQ-ONBOARD-002 -->
## Onboarding MUST adopt existing issue keys so sync never duplicates

Adoption is what makes onboarding safe: the first `sync` after onboarding
must recognize every imported issue as already-created.

implementations:
  - taskship/onboard.py
  - taskship/state.py:StateStore.record

## Acceptance
<!-- id: REQ-ONBOARD-002.A1 -->
- For every imported node, the Jira issue key and current field snapshot are
  recorded in `.taskship/state.json` at import time.
<!-- id: REQ-ONBOARD-002.A2 -->
- `taskship sync --dry-run` immediately after an unmodified onboard reports
  zero creates — every imported node resolves to update or skip.

<!-- id: REQ-ONBOARD-003 -->
## Imported tasks MUST keep their Jira descriptions untouched by sync

Teams wrote those descriptions by hand; adoption must not flatten or
overwrite them with template-rendered ADF.

implementations:
  - taskship/builtin_templates/imported.yaml
  - taskship/onboard.py

## Acceptance
<!-- id: REQ-ONBOARD-003.A1 -->
- Imported tasks whose type cannot be inferred from existing
  `taskship:type:*` labels get the built-in type `imported`; a task that DOES
  carry a `taskship:type:*` label (a previously TaskShip-managed issue) keeps
  that type when its template renders with the recoverable fields — a kept
  type whose template's required fields cannot be recovered from the import
  is downgraded to `imported` and reported in the summary, never allowed to
  make the first sync unrenderable.
<!-- id: REQ-ONBOARD-003.A2 -->
- Sync never includes a description field in the payload of an
  `imported`-type task: after onboard + sync, every imported issue's Jira
  description is byte-identical to what it was before onboarding.
<!-- id: REQ-ONBOARD-003.A3 -->
- An `imported`-type task still syncs its structural fields (title, labels,
  hierarchy) like any other task.

<!-- id: REQ-ONBOARD-004 -->
## Onboarding MUST be a guarded one-time bootstrap

Re-running onboard against a live plan is the bidirectional-sync trap
(VISION-DOC decision 1); the command refuses it.

implementations:
  - taskship/onboard.py

## Acceptance
<!-- id: REQ-ONBOARD-004.A1 -->
- When `plan.yaml` already exists in the target directory, `taskship onboard`
  fails with an error explaining that onboarding is one-time, and changes
  neither `plan.yaml` nor `.taskship/state.json`; `--force` overrides after
  the error text names what will be replaced.
<!-- id: REQ-ONBOARD-004.A2 -->
- A failed or interrupted onboard (network error mid-import) leaves no
  partial `plan.yaml` and no partial state — both are written only after the
  full import succeeds.

<!-- id: REQ-ONBOARD-005 -->
## Onboarding MUST print a review summary

The human review that follows needs a map: what came in, what was skipped,
what deserves pruning.

implementations:
  - taskship/onboard.py
  - taskship/cli.py:onboard

## Acceptance
<!-- id: REQ-ONBOARD-005.A1 -->
- On success the command prints counts (epics/stories/tasks imported, issues
  skipped by category) and the epic → story tree (reusing the `review`
  renderer), ending with the next steps: review/prune `plan.yaml`, then
  `taskship sync --dry-run`.
<!-- id: REQ-ONBOARD-005.A2 -->
- The summary flags likely-noise candidates — e.g. epics with zero open
  stories and done-status leftovers — so the reviewer knows where to prune
  first.
