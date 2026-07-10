---
id: SITE-DOC
title: TaskShip marketing landing site
owner: "@selvakumar"
priority: medium
version: 2
---

<!-- id: SITE-DOC -->
# TaskShip landing site

A single-page marketing landing site for TaskShip, built with **Astro** and
served as static HTML. The audience is **technical product managers** — people
comfortable with a terminal who feel the pain of hand-building Jira hierarchies.
The site's job is to make them understand, in one scroll, what TaskShip is
(plan-as-code over Jira), why it's better than clicking in Jira, and how to
install it.

Design direction (one, no variations): **clean modern SaaS, light theme**. The
hero centres on TaskShip's two-part story — the **brief → plan → Jira pipeline**
and a **terminal/CLI session** — so a technical reader instantly gets the shape
of the tool. The primary call to action everywhere is **install / get started**
via pip + CLI.

Standard full-page structure, top to bottom: hero → problem → how-it-works →
features → final CTA (+ footer). The content is grounded in the product this
repo implements: plan-as-code (`plan.yaml`), idempotent Jira sync, typed
task templates, and the two front doors (CLI + MCP). Copy must not overclaim
beyond what the shipped `taskship` CLI does (`init` / `plan` / `review` /
`sync` / `status`).

Non-goals for v1: no blog, no auth, no pricing page, no backend, no analytics
beyond a placeholder, no A/B variations.

<!-- id: REQ-SITE-001 -->
## The site MUST be a static Astro build with a light, responsive SaaS theme

The site MUST be an Astro project that builds to static HTML/CSS with no runtime
server, MUST render in a light clean-SaaS visual style, and MUST be legible and
usable from a narrow mobile width up to a wide desktop.

implementations:

## Acceptance
<!-- id: REQ-SITE-001.A1 -->
- `npm run build` (Astro) produces a static site under the build output
  directory with no server-side runtime required to serve it.
<!-- id: REQ-SITE-001.A2 -->
- The rendered page uses a light background as its base theme (not a dark
  theme) and a single consistent type/colour system across all sections.
<!-- id: REQ-SITE-001.A3 -->
- At a 375px-wide viewport every section is readable with no horizontal
  overflow, and the layout reflows to multi-column at desktop widths.

<!-- id: REQ-SITE-002 -->
## The hero MUST show the brief→plan→Jira pipeline, a CLI session, and the install CTA

Above the fold, the hero MUST communicate TaskShip's shape at a glance: a
one-line value proposition, a visual of the **brief → plan.yaml → Jira**
pipeline, a representative **terminal/CLI session**, and the primary
install/get-started call to action.

implementations:

## Acceptance
<!-- id: REQ-SITE-002.A1 -->
- The hero contains a headline and subhead stating that TaskShip turns a product
  brief into a reviewable plan-as-code and syncs it into Jira idempotently.
<!-- id: REQ-SITE-002.A2 -->
- The hero renders a pipeline diagram with three labelled stages in order —
  brief, plan (`plan.yaml`), and Jira — showing the left-to-right flow between them.
<!-- id: REQ-SITE-002.A3 -->
- The hero renders a terminal/CLI block showing real `taskship` commands
  (e.g. `taskship plan …`, `taskship sync --dry-run`) with representative output.
<!-- id: REQ-SITE-002.A4 -->
- The hero contains a primary CTA to install / get started; it is the most
  visually prominent action above the fold.

<!-- id: REQ-SITE-003 -->
## A problem section MUST articulate the core problems TaskShip solves

The site MUST include a section that names the concrete pains a technical PM
feels today — so the reader recognises their own situation before the solution
is pitched.

implementations:

## Acceptance
<!-- id: REQ-SITE-003.A1 -->
- The section states the "planning by clicking in Jira is slow, inconsistent,
  and hard to review" problem in the reader's terms.
<!-- id: REQ-SITE-003.A2 -->
- The section names at least three distinct problems, including inconsistent
  ticket shape and the lack of a reviewable/diffable plan before it hits the board.
<!-- id: REQ-SITE-003.A3 -->
- Each problem is paired with the TaskShip capability that addresses it
  (plan-as-code, typed templates, idempotent sync) without yet explaining the how.

<!-- id: REQ-SITE-004 -->
## A how-it-works section MUST make the brief→plan→sync flow clear

The site MUST include a section that walks the reader through the actual
workflow in ordered steps, so a first-time visitor understands how they'd use
TaskShip end to end.

implementations:

## Acceptance
<!-- id: REQ-SITE-004.A1 -->
- The section presents the workflow as ordered, numbered steps covering:
  describe a brief → generate/review `plan.yaml` → dry-run → sync to Jira → check status.
<!-- id: REQ-SITE-004.A2 -->
- At least one step shows the plan-as-code (a `plan.yaml` snippet) and at least
  one shows the idempotent sync (create/update/skip), reflecting the real tool.
<!-- id: REQ-SITE-004.A3 -->
- The section states that re-running sync never duplicates — it diffs and
  updates — since that is TaskShip's core differentiator.

<!-- id: REQ-SITE-005 -->
## A features section MUST present TaskShip's differentiators

The site MUST include a features section that presents TaskShip's distinct
capabilities as scannable items, each with a short title and one-line explanation.

implementations:

## Acceptance
<!-- id: REQ-SITE-005.A1 -->
- The section presents at least four features as discrete cards/items, covering
  plan-as-code, idempotent sync, typed task templates, and the two front doors (CLI + MCP).
<!-- id: REQ-SITE-005.A2 -->
- Each feature item has a distinct title and a concise supporting line; no item
  is a duplicate of another.

<!-- id: REQ-SITE-006 -->
## A final CTA MUST give a copy-paste install / get-started path

The page MUST close with a call-to-action section that gives the reader an
immediate, copy-pasteable way to install and start using TaskShip via pip + CLI.

implementations:

## Acceptance
<!-- id: REQ-SITE-006.A1 -->
- The final CTA shows a copyable install command (pip) and the first CLI command
  to run (`taskship init` or `taskship plan …`).
<!-- id: REQ-SITE-006.A2 -->
- The install command block is selectable/copyable as text (real text, not an
  image of a command).

<!-- id: REQ-SITE-007 -->
## Install references MUST point at the published PyPI release

TaskShip 0.1.0 is published on PyPI as `taskship`. Every install reference on
the site MUST use the real published package name, and the site MUST link to
the PyPI project page so a reader can verify the release.

implementations:
  - site/src/components/CTA.astro:CTA

## Acceptance
<!-- id: REQ-SITE-007.A1 -->
- Every install command shown on the site reads `pip install taskship`
  (the name published on PyPI), with no placeholder or pre-release caveat
  ("coming soon", TestPyPI, git-clone install) remaining anywhere on the page.
<!-- id: REQ-SITE-007.A2 -->
- At least one install CTA (hero or final CTA) links to
  `https://pypi.org/project/taskship/`.

<!-- id: REQ-SITE-008 -->
## The site MUST include a setup guide from install to a synced Jira product

The site MUST include a guide that walks a first-time user end to end: install
TaskShip, connect it to their Jira site, define a product plan as code, and
sync it into a Jira project. The guide is grounded in the shipped CLI — every
command and configuration key it shows must exist in the `taskship` package.

The guide lives on its own page (`/guide`) rather than a landing-page section,
so the landing page keeps its one-scroll pitch.

implementations:
  - site/src/pages/guide.astro:guide

## Acceptance
<!-- id: REQ-SITE-008.A1 -->
- The guide is reachable from the landing page via the nav and via a link in
  the final CTA section.
<!-- id: REQ-SITE-008.A2 -->
- The guide presents ordered steps covering, in order: install from PyPI
  (`pip install taskship`) → scaffold (`taskship init`) → connect Jira →
  author the plan (`taskship plan "<brief>"` or hand-editing `plan.yaml`) →
  review (`taskship review`) → preview (`taskship sync --dry-run`) → sync
  (`taskship sync`) → verify (`taskship status`).
<!-- id: REQ-SITE-008.A3 -->
- The Jira-connection step names the real configuration surface: the
  `jira_project` key in `plan.yaml`, the `JIRA_BASE_URL`, `JIRA_EMAIL`, and
  `JIRA_TOKEN` environment variables, the optional `JIRA_SPRINT_FIELD`
  variable, and where to create an Atlassian API token.
<!-- id: REQ-SITE-008.A4 -->
- Every command and config snippet in the guide is rendered as selectable,
  copy-pasteable text, and none references a command, flag, or key that the
  shipped CLI does not have.
<!-- id: REQ-SITE-008.A5 -->
- The guide states that `sync` is idempotent (re-running diffs and updates,
  never duplicates), consistent with the landing page's claim.
