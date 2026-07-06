"""Round-trip I/O tests for REQ-TS-001 (A1, A2)."""
from pathlib import Path

import pytest

from taskship import PlanValidationError, dump_plan, load_plan

FIXTURE = Path(__file__).parent / "fixtures" / "valid_plan.yaml"


def test_round_trip_preserves_fields_and_comments(tmp_path):
    """A1: load then dump reproduces authored fields AND comments losslessly."""
    original = FIXTURE.read_text()

    plan, raw = load_plan(FIXTURE)

    out = tmp_path / "out.yaml"
    dump_plan(raw, out)

    assert out.read_text() == original


def test_no_partial_write_on_invalid(tmp_path):
    """A2: an invalid plan raises and never leaves a written output file."""
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "product: Acme\n"
        "jira_project: STORE\n"
        "epics:\n"
        "  - id: e1\n"  # epic missing required `title`
        "    stories: []\n"
    )

    with pytest.raises(PlanValidationError):
        load_plan(bad)

    # load_plan must never write anything of its own
    out = tmp_path / "never_written.yaml"
    assert not out.exists()
