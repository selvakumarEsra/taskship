---
id: KNOW-DOC
title: Knowledge files — curated domain context for the agent door
owner: "@selvakumar"
priority: high
version: 1
---

<!-- id: KNOW-DOC -->
# Knowledge files — curated domain context for the agent door

VISION-DOC decision 4: domain knowledge lives as plain markdown files next to
the plan — seeded from imported Jira content at onboarding, reviewed and
hand-curated by the team thereafter, and read by the agent whenever it
interviews a reporter, splits an epic, or facilitates a ceremony. The agent
always reads files; there is no hidden index, no embeddings, no store.

Knowledge is what turns the agent's questioning from generic form-filling into
domain-aware interviewing: templates say *what* must be answered (required
fields); knowledge files say *what to ask about this domain specifically*
(its terms, its recurring failure patterns, its intake questions).

Design decisions: one file per epic (`knowledge/<epic-id>.md`) plus an
optional project-wide `knowledge/domain.md` glossary; files are free-form
markdown with no schema beyond a title — curation friction must be near zero;
seeding is deterministic (structure extraction only — epic description, story
inventory, placeholder sections), never an LLM call (REQ-VISION-001); absent
knowledge is never an error — every consumer degrades gracefully to
plan-and-templates-only.

Non-goals: no knowledge search/index; no automatic knowledge updates after
seeding (curation is human); no knowledge for stories/tasks (the epic is the
domain unit); no enforcement that knowledge stays current.

<!-- id: REQ-KNOW-001 -->
## Knowledge MUST live as per-epic markdown files under `knowledge/`

The convention every consumer relies on: `knowledge/<epic-id>.md` for an
epic's domain context, `knowledge/domain.md` for project-wide terms.

implementations:
  - taskship/knowledge.py

## Acceptance
<!-- id: REQ-KNOW-001.A1 -->
- Knowledge for epic `<epic-id>` is resolved from `knowledge/<epic-id>.md`
  relative to the project directory, and project-wide knowledge from
  `knowledge/domain.md`; no other locations are consulted.
<!-- id: REQ-KNOW-001.A2 -->
- A missing knowledge directory or file is not an error anywhere: consumers
  receive an empty result and proceed.
<!-- id: REQ-KNOW-001.A3 -->
- Files are read as plain markdown text — no frontmatter, schema, or naming
  rules are enforced beyond the `<epic-id>.md` filename convention.

<!-- id: REQ-KNOW-002 -->
## Onboarding MUST seed first-draft knowledge files deterministically

The dev lead reviews knowledge in the same pass as structure. Seeding
extracts what the import already knows — it never calls a model.

implementations:
  - taskship/knowledge.py
  - taskship/onboard.py

## Acceptance
<!-- id: REQ-KNOW-002.A1 -->
- A successful `taskship onboard` writes `knowledge/<epic-id>.md` for every
  imported epic, containing: the epic's title and description text, its story
  inventory (titles), and empty placeholder sections for domain terms, intake
  questions, and known failure patterns.
<!-- id: REQ-KNOW-002.A2 -->
- Seeding never overwrites: an existing `knowledge/<epic-id>.md` is left
  byte-identical and reported as skipped in the onboard summary.
<!-- id: REQ-KNOW-002.A3 -->
- Seeding is deterministic — two onboards of the same project content produce
  identical knowledge files — and makes no LLM/API-model calls.
<!-- id: REQ-KNOW-002.A4 -->
- Seeded files are counted in the onboard summary (written / skipped), and a
  failed onboard writes no knowledge files (same atomicity as the plan).

<!-- id: REQ-KNOW-003 -->
## Both front doors MUST expose knowledge retrieval

The agent interviewing a reporter needs the epic's knowledge in one call;
a human wants to eyeball it from the terminal.

implementations:
  - taskship/cli.py:knowledge
  - taskship/mcp_server.py:get_knowledge

## Acceptance
<!-- id: REQ-KNOW-003.A1 -->
- `taskship knowledge` lists the available knowledge files with their epic
  ids; `taskship knowledge <epic-id>` prints that file's content (combined
  with `domain.md` when present, clearly separated).
<!-- id: REQ-KNOW-003.A2 -->
- The MCP server exposes a `get_knowledge` tool over the same engine
  function: given an epic id it returns the epic's knowledge text plus the
  project-wide domain text; given no id it returns the list of available
  files.
<!-- id: REQ-KNOW-003.A3 -->
- An unknown epic id returns an empty/clean result naming the available
  knowledge files — not an error — on both doors.

<!-- id: REQ-KNOW-004 -->
## `taskship init` MUST scaffold the knowledge directory

Greenfield projects (no Jira to seed from) still need the convention
discoverable from day one.

implementations:
  - taskship/scaffold.py:init_project

## Acceptance
<!-- id: REQ-KNOW-004.A1 -->
- `taskship init` creates `knowledge/` containing a `domain.md` starter that
  explains the convention (one file per epic id, what sections help the
  agent) with placeholder sections matching the seeded shape.
<!-- id: REQ-KNOW-004.A2 -->
- Init stays idempotent: existing knowledge files are never overwritten.
