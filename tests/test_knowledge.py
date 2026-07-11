"""KNOW-DOC — knowledge files: curated domain context for the agent door.

REQ-KNOW-001: knowledge lives as per-epic markdown under `knowledge/`.
REQ-KNOW-002: onboarding seeds first-draft files deterministically (no LLM).
REQ-KNOW-003: both front doors expose knowledge retrieval over one engine.
REQ-KNOW-004: `taskship init` scaffolds the knowledge directory.
"""
from taskship.knowledge import (
    KnowledgeSeed,
    domain_knowledge_path,
    epic_knowledge_path,
    flatten_adf,
    format_knowledge,
    get_knowledge,
    list_knowledge,
    read_domain_knowledge,
    read_epic_knowledge,
    render_seed,
    scaffold_knowledge,
    seed_knowledge,
)


def _adf(*paragraphs: str) -> dict:
    return {
        "version": 1, "type": "doc",
        "content": [
            {"type": "paragraph",
             "content": [{"type": "text", "text": p}]}
            for p in paragraphs
        ],
    }


# --- REQ-KNOW-001: resolve / read ------------------------------------------

def test_a1_epic_knowledge_resolves_only_from_knowledge_dir(tmp_path):
    kdir = tmp_path / "knowledge"
    kdir.mkdir()
    (kdir / "checkout.md").write_text("# Checkout\n\nDomain notes.")
    assert read_epic_knowledge(tmp_path, "checkout") == "# Checkout\n\nDomain notes."
    assert epic_knowledge_path(tmp_path, "checkout") == kdir / "checkout.md"


def test_a1_domain_knowledge_resolves_from_domain_md(tmp_path):
    kdir = tmp_path / "knowledge"
    kdir.mkdir()
    (kdir / "domain.md").write_text("Project glossary.")
    assert read_domain_knowledge(tmp_path) == "Project glossary."
    assert domain_knowledge_path(tmp_path) == kdir / "domain.md"


def test_a2_missing_dir_or_file_is_never_an_error(tmp_path):
    # No knowledge/ directory at all.
    assert read_epic_knowledge(tmp_path, "nope") == ""
    assert read_domain_knowledge(tmp_path) == ""
    assert list_knowledge(tmp_path) == []
    # Directory exists but the file does not.
    (tmp_path / "knowledge").mkdir()
    assert read_epic_knowledge(tmp_path, "nope") == ""


def test_a3_files_are_plain_text_no_schema(tmp_path):
    kdir = tmp_path / "knowledge"
    kdir.mkdir()
    # Arbitrary content with no frontmatter or naming rules is returned verbatim.
    (kdir / "x.md").write_text("just prose, no ## sections required")
    assert read_epic_knowledge(tmp_path, "x") == "just prose, no ## sections required"


def test_a1_domain_md_is_not_listed_as_an_epic_file(tmp_path):
    kdir = tmp_path / "knowledge"
    kdir.mkdir()
    (kdir / "domain.md").write_text("glossary")
    (kdir / "epic-a.md").write_text("a")
    (kdir / "epic-b.md").write_text("b")
    assert list_knowledge(tmp_path) == ["epic-a", "epic-b"]


# --- ADF flattening --------------------------------------------------------

def test_flatten_adf_extracts_plain_text():
    doc = _adf("First paragraph.", "Second paragraph.")
    assert flatten_adf(doc) == "First paragraph.\nSecond paragraph."


def test_flatten_adf_accepts_plain_string_and_none():
    assert flatten_adf("already text") == "already text"
    assert flatten_adf(None) == ""
    assert flatten_adf(123) == ""


# --- REQ-KNOW-002: deterministic seeding -----------------------------------

def test_a1_seed_has_title_description_stories_and_placeholders(tmp_path):
    seed = KnowledgeSeed(epic_id="checkout", title="Checkout revamp",
                         description="Rework the checkout flow.",
                         story_titles=["Guest flow", "Saved cards"])
    report = seed_knowledge(tmp_path, [seed])
    assert report.written == ["checkout"]
    text = (tmp_path / "knowledge" / "checkout.md").read_text()
    assert "# Checkout revamp" in text
    assert "Rework the checkout flow." in text
    assert "- Guest flow" in text and "- Saved cards" in text
    assert "## Domain terms" in text
    assert "## Intake questions" in text
    assert "## Known failure patterns" in text


def test_a2_seeding_never_overwrites_and_reports_skipped(tmp_path):
    kdir = tmp_path / "knowledge"
    kdir.mkdir()
    hand_curated = "# Mine\n\nDo not clobber."
    (kdir / "checkout.md").write_text(hand_curated)
    report = seed_knowledge(
        tmp_path,
        [KnowledgeSeed(epic_id="checkout", title="Checkout", description="x")],
    )
    assert report.skipped == ["checkout"]
    assert report.written == []
    assert (kdir / "checkout.md").read_text() == hand_curated  # byte-identical


def test_a3_seeding_is_deterministic_byte_identical(tmp_path):
    seed = KnowledgeSeed(epic_id="e", title="Epic", description="desc",
                         story_titles=["S1", "S2"])
    first = render_seed(seed)
    second = render_seed(seed)
    assert first == second
    # No timestamps / randomness leak into the bytes.
    import re
    assert not re.search(r"\d{4}-\d{2}-\d{2}", first)


def test_a1_seed_handles_empty_description_and_no_stories(tmp_path):
    text = render_seed(KnowledgeSeed(epic_id="e", title="Bare epic"))
    assert "# Bare epic" in text
    assert "_No description" in text
    assert "_No stories" in text


# --- REQ-KNOW-003: retrieval over one engine -------------------------------

def test_a1_get_knowledge_no_id_lists_available(tmp_path):
    kdir = tmp_path / "knowledge"
    kdir.mkdir()
    (kdir / "a.md").write_text("a")
    (kdir / "b.md").write_text("b")
    result = get_knowledge(tmp_path)
    assert result["epic_id"] is None
    assert result["available"] == ["a", "b"]


def test_a1_get_knowledge_with_id_returns_epic_and_domain(tmp_path):
    kdir = tmp_path / "knowledge"
    kdir.mkdir()
    (kdir / "checkout.md").write_text("epic body")
    (kdir / "domain.md").write_text("domain body")
    result = get_knowledge(tmp_path, "checkout")
    assert result["found"] is True
    assert result["epic"] == "epic body"
    assert result["domain"] == "domain body"


def test_a1_format_combines_epic_and_domain_clearly_separated(tmp_path):
    kdir = tmp_path / "knowledge"
    kdir.mkdir()
    (kdir / "checkout.md").write_text("EPIC-CONTENT")
    (kdir / "domain.md").write_text("DOMAIN-CONTENT")
    text = format_knowledge(get_knowledge(tmp_path, "checkout"))
    assert "EPIC-CONTENT" in text
    assert "DOMAIN-CONTENT" in text
    # A visible divider separates the two.
    assert "domain.md" in text


def test_a3_unknown_epic_id_is_clean_result_naming_available(tmp_path):
    kdir = tmp_path / "knowledge"
    kdir.mkdir()
    (kdir / "known.md").write_text("k")
    result = get_knowledge(tmp_path, "missing")
    assert result["found"] is False
    assert result["epic"] == ""
    assert result["available"] == ["known"]
    text = format_knowledge(result)
    assert "missing" in text
    assert "known" in text  # names what IS available


# --- REQ-KNOW-004: init scaffold -------------------------------------------

def test_a1_scaffold_creates_domain_starter_with_placeholder_sections(tmp_path):
    path = scaffold_knowledge(tmp_path)
    assert path == tmp_path / "knowledge" / "domain.md"
    text = path.read_text()
    # Explains the convention…
    assert "knowledge/<epic-id>.md" in text
    # …with the same placeholder sections a seeded epic file carries.
    assert "## Domain terms" in text
    assert "## Intake questions" in text
    assert "## Known failure patterns" in text


def test_a2_scaffold_is_idempotent_never_overwrites(tmp_path):
    kdir = tmp_path / "knowledge"
    kdir.mkdir()
    (kdir / "domain.md").write_text("hand-written")
    scaffold_knowledge(tmp_path)
    assert (kdir / "domain.md").read_text() == "hand-written"
