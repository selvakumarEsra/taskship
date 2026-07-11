---
id: VISION-DOC
title: TaskShip vision — agent-PM over deterministic rails
owner: "@selvakumar"
priority: high
version: 1
---

<!-- id: VISION-DOC -->
# TaskShip vision — agent-PM over deterministic rails

TaskShip's end state: a team onboards an existing Jira project with one
command, reviews the imported structure once, and from then on an agent runs
the project-management drudgery — interviewing reporters about production
observations, helping product owners split epics, assembling and facilitating
the daily ceremony — while every structural decision remains a reviewable text
file and every Jira write remains idempotent.

This document records the ratified decisions that govern all future capability
specs, and carries the small set of invariants that keep the product a tool
rather than a platform. The capability specs themselves (onboarding, knowledge
files, review dashboard, ceremony view, confirmed-intake flow) are authored
separately and must conform to these decisions.

Ratified decisions (grilled 2026-07-11):

1. **Plan-canonical after adoption.** Onboarding from a Jira key is a one-time
   bootstrap: import → human review → adopt existing issue keys into sync
   state. Thereafter `plan.yaml` owns structure and content; Jira edits that
   drift from the plan surface as sync conflicts, never silent merges. No
   bidirectional sync engine, ever.
2. **The interview is the review.** Event intakes (ops observations, UAT
   issues) arriving through the agent door may sync to Jira immediately on
   the reporter's confirmation, because the agent's structured questioning —
   template required fields plus knowledge files — substitutes for plan
   review. The CLI verbs stay plan-only. The product door (epics/features)
   is always review-gated.
3. **Decisions route to their existing owners.** Ceremony outcomes:
   assignee and sprint go into the plan (reviewable, cascade machinery);
   status, priority, and start/end dates are written directly to Jira, into
   fields sync never touches, so they survive every sync by construction.
4. **Knowledge is seeded then curated files.** Domain knowledge lives as
   plain markdown under the project (seeded from imported Jira content at
   onboarding, reviewed and hand-curated thereafter). The agent reads files;
   there is no hidden index.
5. **The UI is a review tool, not a product surface.** The onboarding review
   runs as a local loopback page that writes `plan.yaml` and dies with the
   terminal. No hosted backend, no accounts.
6. **The agent door is the intelligence.** TaskShip ships no LLM calls; the
   MCP-connected agent does the questioning, splitting, and facilitation
   through TaskShip's deterministic tools.
7. **The harness is the clock and the room.** TaskShip provides agenda and
   decision-routing verbs; convening (cron/scheduling) and presence
   (terminal, chat channel) belong to the agent harness.

<!-- id: REQ-VISION-001 -->
## TaskShip MUST remain deterministic rails

The package's value is that everything it does is reproducible and
reviewable. Intelligence, scheduling, and channel presence belong to the
agent harness driving it.

implementations:

## Acceptance
<!-- id: REQ-VISION-001.A1 -->
- The `taskship` package makes no LLM/API-model calls: no model-provider
  dependency appears in `pyproject.toml` and no capability requires a model
  API key to function.
<!-- id: REQ-VISION-001.A2 -->
- The package contains no scheduler/daemon and no chat-channel integrations;
  recurring behaviour is documented as the harness's job (e.g. a cron'd agent
  session).
<!-- id: REQ-VISION-001.A3 -->
- Every capability that mutates `plan.yaml` or Jira is invocable as a plain
  CLI command and (where its inputs allow) an MCP tool over the same engine —
  an agent is never *required* to operate TaskShip.

<!-- id: REQ-VISION-002 -->
## The plan MUST stay canonical after adoption

Onboarding must not quietly convert TaskShip into a two-way sync engine.

implementations:

## Acceptance
<!-- id: REQ-VISION-002.A1 -->
- After a project is onboarded and adopted, a Jira-side structural edit
  (retitle, re-parent) is reported as a conflict or drift by
  `status`/`sync`, never merged silently back into `plan.yaml`.
<!-- id: REQ-VISION-002.A2 -->
- No shipped command rewrites plan structure from Jira after adoption;
  reverse flow is limited to status/board reads and explicit conflict
  reporting.

<!-- id: REQ-VISION-003 -->
## Jira-owned fields MUST survive every sync

The ceremony writes its decisions into Jira; sync must never fight them.

implementations:

## Acceptance
<!-- id: REQ-VISION-003.A1 -->
- Sync payloads never contain Jira priority, status, or start/end date
  fields; a value set in Jira for any of these persists across an arbitrary
  number of `taskship sync` runs.
