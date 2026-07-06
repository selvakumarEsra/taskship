"""REQ-TS-006 — recover the id→key mapping when local state is missing.

A1: with state lost but issues still watermarked, recover keys → zero creates.
A2: a node whose watermark matches nothing is created fresh, key+hash recorded.
A3: every created issue carries the taskship:<id> watermark label.
"""
from taskship import Plan
from taskship.state import StateStore
from taskship.reconcile import reconcile
from tests.fakes import FakeJira

PLAN = {
    "product": "P", "jira_project": "CHK",
    "epics": [{"id": "guest-checkout", "title": "E", "stories": [
        {"id": "guest-flow", "title": "S", "tasks": [
            {"id": "biz-1", "title": "T", "type": "biz-spec"}]}]}],
}


def test_a1_recovers_keys_from_watermark_when_state_lost(tmp_path):
    jira = FakeJira()
    reconcile(Plan.from_mapping(PLAN), jira, StateStore(tmp_path / "s1.json"))
    # jira.external_index is now populated (simulates real issues carrying labels).
    creates_after_first = len(jira.create_calls)

    # State is lost: a brand-new, empty store at a fresh path.
    lost_state = StateStore(tmp_path / "recovered.json")
    report = reconcile(Plan.from_mapping(PLAN), jira, lost_state)

    assert report.created == []                      # zero creates — recovered instead
    assert len(jira.create_calls) == creates_after_first  # no NEW create calls
    # recovery re-populated the state so subsequent syncs can skip
    assert lost_state.key("guest-checkout") == "CHK-101"


def test_a2_unmatched_watermark_is_created_fresh(tmp_path):
    jira = FakeJira()  # empty external_index → nothing to recover
    state = StateStore(tmp_path / "s.json")
    report = reconcile(Plan.from_mapping(PLAN), jira, state)

    assert len(report.created) == 3
    assert state.key("guest-checkout/guest-flow/biz-1") is not None


def test_a3_every_created_issue_carries_watermark_label(tmp_path):
    jira = FakeJira()
    reconcile(Plan.from_mapping(PLAN), jira, StateStore(tmp_path / "s.json"))
    for key, issue in jira.issues.items():
        ext_ids = [l for l in issue["labels"] if l.startswith("taskship:")
                   and not l.startswith("taskship:type:")
                   and not l.startswith("taskship:subtype:")]
        assert ext_ids, f"{key} missing watermark label"
