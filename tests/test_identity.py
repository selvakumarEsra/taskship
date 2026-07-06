"""REQ-TS-002 — every node has a stable local identity independent of Jira key.

A1: same title under different parents → distinct fully-qualified ids.
A2: changing title while keeping id → identity unchanged (update, not create).
A3: a node without an explicit id gets a deterministic slug, stable across loads.
"""
from taskship import Plan
from taskship.identity import slug, local_id, qualified_id, iter_nodes


def _plan(data):
    return Plan.from_mapping(data)


def test_slug_is_deterministic_kebab_case():
    assert slug("One-click guest checkout") == "one-click-guest-checkout"
    assert slug("Payment auth p95 < 200ms") == "payment-auth-p95-200ms"
    # Stable: same input, same output, no randomness (A3).
    assert slug("Guest checkout flow") == slug("Guest checkout flow")


def test_local_id_prefers_explicit_then_slug():
    from taskship.model import Task
    assert local_id(Task(id="perf-1", title="Whatever", type="tech-spec")) == "perf-1"
    assert local_id(Task(title="Define guest checkout requirements", type="biz-spec")) == (
        "define-guest-checkout-requirements"
    )


def test_a1_same_title_different_parents_distinct_qualified_ids():
    # Two stories with the SAME title under different epics.
    plan = _plan({
        "product": "P", "jira_project": "CHK",
        "epics": [
            {"id": "epic-a", "title": "A", "stories": [
                {"title": "Shared Flow", "tasks": [{"title": "Do X", "type": "biz-spec"}]}]},
            {"id": "epic-b", "title": "B", "stories": [
                {"title": "Shared Flow", "tasks": [{"title": "Do X", "type": "biz-spec"}]}]},
        ],
    })
    ids = [qid for qid, _node, _level in iter_nodes(plan)]
    # All qualified ids are unique despite the repeated "Shared Flow"/"Do X" titles.
    assert len(ids) == len(set(ids))
    assert "epic-a/shared-flow" in ids
    assert "epic-b/shared-flow" in ids
    assert "epic-a/shared-flow/do-x" in ids
    assert "epic-b/shared-flow/do-x" in ids


def test_a2_title_change_keeps_identity_when_id_pinned():
    before = _plan({
        "product": "P", "jira_project": "CHK",
        "epics": [{"id": "guest-checkout", "title": "One-click guest checkout", "stories": [
            {"id": "guest-flow", "title": "Guest checkout flow", "tasks": []}]}],
    })
    after = _plan({
        "product": "P", "jira_project": "CHK",
        "epics": [{"id": "guest-checkout", "title": "RENAMED epic", "stories": [
            {"id": "guest-flow", "title": "RENAMED story", "tasks": []}]}],
    })
    ids_before = {qid for qid, _n, _l in iter_nodes(before)}
    ids_after = {qid for qid, _n, _l in iter_nodes(after)}
    # Identity is pinned to id, not title — renaming does not change it.
    assert ids_before == ids_after
    assert "guest-checkout" in ids_after
    assert "guest-checkout/guest-flow" in ids_after


def test_a3_missing_id_slug_is_stable_across_loads():
    data = {
        "product": "P", "jira_project": "CHK",
        "epics": [{"title": "One-click guest checkout", "stories": [
            {"title": "Guest checkout flow", "tasks": [
                {"title": "Define guest checkout requirements", "type": "biz-spec"}]}]}],
    }
    ids1 = [qid for qid, _n, _l in iter_nodes(_plan(data))]
    ids2 = [qid for qid, _n, _l in iter_nodes(_plan(data))]
    assert ids1 == ids2  # deterministic, no randomness
    assert "one-click-guest-checkout" in ids1
    assert "one-click-guest-checkout/guest-checkout-flow" in ids1
    assert (
        "one-click-guest-checkout/guest-checkout-flow/define-guest-checkout-requirements"
        in ids1
    )
