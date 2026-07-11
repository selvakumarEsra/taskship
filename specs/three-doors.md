---
id: DOORS-DOC
title: Four doors — ops observations, product features, regression test plans, UAT issues
owner: "@selvakumar"
priority: high
version: 2
---

<!-- id: DOORS-DOC -->
# Four doors into the plan

TaskShip today serves one persona: the technical PM planning product features
(brief → `plan.yaml` → Jira). This document adds two more personas as first-class
"doors" into the **same plan**, so one reviewable tree carries the whole team's
work and the existing sync/ceremony machinery serves everyone:

1. **Ops door** — the BAU/support team files production observations as typed
   tasks in a dedicated intake lane. Observations land unprioritized; the team
   prioritizes them in Jira during the sprint/kanban ceremony, aided by a
   triage lane in `taskship board`.
2. **Product door** — the existing feature-development flow. Unchanged; named
   here only so the doors are a complete set.
3. **Test door** — the test manager derives one end-to-end regression test-case
   task per story, idempotently, so every new or renamed story automatically
   gets a test-case ticket and re-runs never duplicate.
4. **UAT door** — anyone acceptance-testing product-door work raises defects
   found *before* release as typed tasks parked **under the story they were
   found against** (an epic-level fallback story catches cross-story
   findings). UAT issues are not triaged like observations — they block their
   story's acceptance, so they carry a `bug` label and live where the fix work
   lives, and the epic's rollup stays honest while they're open.

Design decisions (settled): one `plan.yaml` with typed lanes (not one plan per
door); prioritization stays in Jira — TaskShip marks observations with a triage
label and surfaces them in ceremony views but never writes Jira priority;
`taskship observe` is plan-only (observations reach Jira on the next `sync`,
preserving the reviewable-plan contract); `taskship testplan` covers all
non-ops stories with idempotent derived ids; UAT issues park under their story
with a plain `bug` label rather than a Jira `Bug` issue type, and get **no**
triage label — their priority is implied by the story they block.

Non-goals: no Jira `Bug` issue type (observations and UAT issues are Tasks,
consistent with the Epic/Story/Task mapping in `payload.py`); no priority field
in the plan schema; no interactive triage verb; no automatic test execution —
the test-case tickets are planning artifacts for the regression suite, not test
runners; no UAT issue lifecycle tracking beyond Jira's own status (raised →
fixed → retested is the board's job).

<!-- id: REQ-DOORS-001 -->
## An `ops-observation` task template MUST ship as a built-in

The ops door needs a typed shape for production observations, enforcing the
same definition-of-ready discipline the other templates provide: an observation
without impact stated is not actionable in a ceremony.

implementations:
  - taskship/builtin_templates/ops-observation.yaml

## Acceptance
<!-- id: REQ-DOORS-001.A1 -->
- `taskship/builtin_templates/ops-observation.yaml` exists with sections for
  observation (what was seen), impact (who/what is affected), evidence
  (logs/links/metrics), and suggested action; `observation` and `impact` are
  `required` fields.
<!-- id: REQ-DOORS-001.A2 -->
- Rendering an `ops-observation` task missing `observation` or `impact` raises
  `TemplateError` naming the missing field (no blank ticket reaches Jira).
<!-- id: REQ-DOORS-001.A3 -->
- A rendered observation carries the labels `taskship:type:ops-observation`
  and `taskship:triage`, so the board lane and Jira filters can find
  un-prioritized observations.
<!-- id: REQ-DOORS-001.A4 -->
- A team can fork the template into their `templates/` directory and the fork
  overrides the built-in, same as every other template.

<!-- id: REQ-DOORS-002 -->
## `taskship observe` MUST append an observation to the intake lane, plan-only

On-call needs a one-command way to capture an observation without editing YAML
by hand and without touching the rest of the plan. The command is append-only
and makes no Jira calls — the observation reaches the board on the next
`taskship sync`, keeping every ticket reviewable before it lands.

implementations:
  - taskship/cli.py:observe

## Acceptance
<!-- id: REQ-DOORS-002.A1 -->
- `taskship observe "<title>"` appends one `ops-observation` task to the intake
  lane in `plan.yaml`; optional flags supply the template fields (e.g.
  `--impact`, `--evidence`).
<!-- id: REQ-DOORS-002.A2 -->
- When the intake lane is absent, the command creates it: an `ops-intake` epic
  containing a story with `kind: ops`, without modifying any existing epic,
  story, or task node.
<!-- id: REQ-DOORS-002.A3 -->
- The command makes no Jira calls and requires no `JIRA_*` environment
  variables to run.
<!-- id: REQ-DOORS-002.A4 -->
- Running the same `observe` twice appends two distinct tasks (observations are
  events, not idempotent nodes); each gets a unique id so a later sync never
  collides.
<!-- id: REQ-DOORS-002.A5 -->
- The resulting `plan.yaml` still validates against the plan schema; a write
  that would produce an invalid plan is rejected with the schema's node-path
  error and the file is left untouched.

<!-- id: REQ-DOORS-003 -->
## Ceremony views MUST surface a triage lane for un-prioritized observations

The team prioritizes observations during the sprint/kanban ceremony, in Jira.
TaskShip's job is visibility, not decision: `taskship board` groups the
observations awaiting triage so the ceremony can walk them, and TaskShip never
writes Jira's priority field.

implementations:
  - taskship/ceremonies.py

## Acceptance
<!-- id: REQ-DOORS-003.A1 -->
- `taskship board` renders observations from the intake lane in a dedicated
  triage group, ahead of (or clearly separated from) the status-grouped
  product work.
<!-- id: REQ-DOORS-003.A2 -->
- Sync never sets or updates Jira's priority field on any issue, so a priority
  assigned during the ceremony survives every subsequent `taskship sync`.
<!-- id: REQ-DOORS-003.A3 -->
- An empty intake lane renders as an empty (or omitted) triage group, not an
  error.

<!-- id: REQ-DOORS-004 -->
## A `test-case` task template MUST ship as a built-in

The test door needs a typed shape for end-to-end regression test cases so
every derived ticket states what it verifies and how.

implementations:
  - taskship/builtin_templates/test-case.yaml

## Acceptance
<!-- id: REQ-DOORS-004.A1 -->
- `taskship/builtin_templates/test-case.yaml` exists with sections for scope
  (the story behaviour under test), preconditions, steps, and expected result;
  `scope` is a `required` field.
<!-- id: REQ-DOORS-004.A2 -->
- Rendering a `test-case` task missing `scope` raises `TemplateError` naming
  the missing field.
<!-- id: REQ-DOORS-004.A3 -->
- A rendered test case carries the label `taskship:type:test-case` plus a
  label naming its source story (e.g. `taskship:story:<story-id>`), so the
  regression suite for a story is one Jira filter away.

<!-- id: REQ-DOORS-005 -->
## `taskship testplan` MUST derive one test-case task per story, idempotently

The test manager runs one command after the plan changes; every non-ops story
ends up with exactly one end-to-end regression test-case task, and re-running
is always safe — the same guarantee `sync` gives for Jira, applied to the plan.

implementations:
  - taskship/cli.py:testplan

## Acceptance
<!-- id: REQ-DOORS-005.A1 -->
- After `taskship testplan`, every story not in the intake lane (`kind` is not
  `ops`) contains exactly one task of type `test-case`, with a deterministic
  id derived from the story id (e.g. `<story-id>-e2e`) and its `scope` field
  pre-filled from the story title.
<!-- id: REQ-DOORS-005.A2 -->
- Re-running `taskship testplan` on an unchanged plan changes nothing: no
  duplicate test-case tasks, no modification of existing test-case tasks the
  test manager has already edited.
<!-- id: REQ-DOORS-005.A3 -->
- A story added (or renamed with a pinned id) after a previous run gets its
  test-case task on the next run; stories in the ops intake lane and UAT
  fallback stories (`kind: ops` or `kind: uat`) never get one — defect buckets
  are not story behaviour to regression-test.
<!-- id: REQ-DOORS-005.A4 -->
- The command is plan-only (no Jira calls) and the resulting plan validates
  against the schema.

<!-- id: REQ-DOORS-006 -->
## The MCP front door MUST expose the same two verbs

TaskShip's doctrine is two front doors over one engine — whatever the CLI can
do, an agent can do conversationally. The ops and test doors follow it.

implementations:
  - taskship/mcp_server.py:observe
  - taskship/mcp_server.py:derive_testplan

## Acceptance
<!-- id: REQ-DOORS-006.A1 -->
- The MCP server exposes an `observe` tool and a testplan-derivation tool with
  behaviour identical to their CLI counterparts (plan-only, same lane and
  idempotency rules), implemented over the same session/engine functions.
<!-- id: REQ-DOORS-006.A2 -->
- Both tools return the affected node ids so the agent can report what was
  added or skipped.

<!-- id: REQ-DOORS-007 -->
## A `uat-issue` task template MUST ship as a built-in

The UAT door needs a typed shape for acceptance-test defects: a UAT issue that
doesn't state expected-versus-actual behaviour is not actionable by the story's
developer.

implementations:
  - taskship/builtin_templates/uat-issue.yaml

## Acceptance
<!-- id: REQ-DOORS-007.A1 -->
- `taskship/builtin_templates/uat-issue.yaml` exists with sections for expected
  behaviour, actual behaviour, steps to reproduce, severity, and environment;
  `expected` and `actual` are `required` fields.
<!-- id: REQ-DOORS-007.A2 -->
- Rendering a `uat-issue` task missing `expected` or `actual` raises
  `TemplateError` naming the missing field.
<!-- id: REQ-DOORS-007.A3 -->
- A rendered UAT issue carries the labels `taskship:type:uat-issue` and `bug`
  (the plain label Jira board filters key on), and does NOT carry
  `taskship:triage` — UAT issues block their story, they are not ceremony
  triage items.
<!-- id: REQ-DOORS-007.A4 -->
- A team can fork the template into their `templates/` directory and the fork
  overrides the built-in.

<!-- id: REQ-DOORS-008 -->
## `taskship raise` MUST park a UAT issue under the story it was found against

Whoever runs UAT needs a one-command way to file a defect against the story
under acceptance, keeping the defect co-located with the work it blocks. Like
`observe`, `raise` is an event: plan-only, append-only, never idempotent.

implementations:
  - taskship/cli.py:raise_issue
  - taskship/session.py:TaskShipSession.raise_issue

## Acceptance
<!-- id: REQ-DOORS-008.A1 -->
- `taskship raise "<title>" --story <story-id>` appends one `uat-issue` task
  under that story; optional flags supply the template fields (e.g.
  `--expected`, `--actual`, `--steps`, `--severity`).
<!-- id: REQ-DOORS-008.A2 -->
- The appended task carries a `taskship:story:<story-id>` label naming the
  story it was raised against; when `--test <test-case-id>` names the failed
  regression test case, a `taskship:test:<test-case-id>` label is added too.
<!-- id: REQ-DOORS-008.A3 -->
- `taskship raise "<title>" --epic <epic-id>` (a cross-story finding) parks the
  issue in that epic's `<epic-id>-uat` fallback story, creating the story if
  absent without modifying any existing node; exactly one of `--story` /
  `--epic` must be given.
<!-- id: REQ-DOORS-008.A4 -->
- An unknown `--story` or `--epic` id fails with an error naming the id;
  `plan.yaml` is left untouched.
<!-- id: REQ-DOORS-008.A5 -->
- The command is plan-only (no Jira calls, no `JIRA_*` env needed); raising the
  same title twice appends two distinct tasks with unique ids; the resulting
  plan validates against the schema.

<!-- id: REQ-DOORS-009 -->
## The MCP front door MUST expose `raise` with identical behaviour

Two front doors over one engine: an agent assisting a UAT session files the
defect the same way the CLI does.

implementations:
  - taskship/mcp_server.py:raise_issue

## Acceptance
<!-- id: REQ-DOORS-009.A1 -->
- The MCP server exposes a raise tool with behaviour identical to the CLI verb
  (same parking rules, labels, event semantics), implemented over the same
  session engine method.
<!-- id: REQ-DOORS-009.A2 -->
- The tool returns the new task's id and the story it was parked under.
