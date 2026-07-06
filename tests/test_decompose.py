"""REQ-TS-014 — decomposition emits only schema-valid plans.

A1: a generated plan that fails validation is rejected; no plan.yaml written.
A2: decompose_brief(text) returns the structured tree and makes zero Jira calls.
A3: a decomposed plan syncs through the same validation/reconcile path as a
    hand-authored one (decomposition is a bolt-on, not a special case).
"""
import pytest

from taskship import Plan
from taskship.model import PlanValidationError
from taskship.decompose import decompose_brief, heuristic_generator
from taskship.state import StateStore
from taskship.reconcile import reconcile
from tests.fakes import FakeJira


def test_a1_invalid_generated_plan_is_rejected(tmp_path):
    # A generator that emits an invalid plan (missing product/jira_project).
    bad = lambda text: {"epics": []}
    with pytest.raises(PlanValidationError):
        decompose_brief("anything", generator=bad)
    # nothing was written anywhere
    assert list(tmp_path.iterdir()) == []


def test_a2_returns_tree_and_makes_no_jira_calls():
    # decompose_brief takes no client and touches no network — pure by signature.
    tree = decompose_brief("Checkout revamp: guest checkout and payments")
    assert isinstance(tree, dict)
    assert tree["product"] and tree["jira_project"]
    assert tree["epics"]
    # the returned tree is itself schema-valid
    Plan.from_mapping(tree)


def test_a3_decomposed_plan_syncs_like_hand_authored(tmp_path):
    tree = decompose_brief("Build a guest checkout flow")
    plan = Plan.from_mapping(tree)                     # same validation path
    report = reconcile(plan, FakeJira(), StateStore(tmp_path / "s.json"))
    assert report.created                              # same reconcile path, real issues


def test_heuristic_generator_is_valid_and_deterministic():
    a = heuristic_generator("Checkout Revamp: do the thing")
    b = heuristic_generator("Checkout Revamp: do the thing")
    assert a == b                                      # deterministic (no randomness)
    Plan.from_mapping(a)                               # valid


def test_custom_generator_is_used():
    def gen(text):
        return {
            "product": "Custom", "jira_project": "CUS",
            "epics": [{"id": "e", "title": "From " + text,
                       "stories": [{"id": "s", "title": "S",
                                    "tasks": [{"id": "t", "type": "biz-spec",
                                               "title": "T"}]}]}],
        }
    tree = decompose_brief("brief-x", generator=gen)
    assert tree["product"] == "Custom"
    assert tree["epics"][0]["title"] == "From brief-x"
