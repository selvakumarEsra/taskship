---
slug: per-node-render-error-boundary
created: 2026-07-11
label: sync
---
# Move per-task ADF rendering inside reconcile's per-node error boundary

`build_payloads()` renders every task's ADF before `reconcile()`'s per-node
try/except loop, so one task failing template validation (e.g. an
`ops-observation` created without `--impact` — the first built-in template
with required fields) aborts the entire sync at build time instead of being
reported as a single per-node error alongside the rest of the plan syncing.
Surfaced while implementing REQ-DOORS-002; no acceptance criterion violated —
the designed observe → fill impact → sync flow works — but the failure mode
is all-or-nothing where the reconcile loop's contract ("one bad node must not
abort the whole sync") suggests per-node isolation.

## Grounding
- taskship/payload.py:build_payloads
- taskship/reconcile.py
- taskship/templates.py:render_adf
