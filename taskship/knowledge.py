"""Knowledge files — curated domain context for the agent door (KNOW-DOC).

Domain knowledge lives as plain markdown files next to the plan (VISION-DOC
decision 4): ``knowledge/<epic-id>.md`` for an epic's domain context and an
optional project-wide ``knowledge/domain.md`` glossary. The agent always reads
files — there is no hidden index, no embeddings, no store.

This module is the engine both front doors drive:

* resolve/read (REQ-KNOW-001): knowledge for epic ``X`` resolves ONLY from
  ``knowledge/X.md`` relative to the project dir; project-wide from
  ``knowledge/domain.md``. A missing directory or file is never an error —
  consumers receive an empty result and proceed. Files are plain markdown; no
  frontmatter, schema, or naming rules are enforced beyond the filename.
* seed (REQ-KNOW-002): onboarding writes a first-draft file per imported epic
  deterministically — structure extraction only (title, description text, story
  inventory, empty placeholder sections). No LLM/API-model calls (REQ-VISION-001).
  Seeding never overwrites and is byte-reproducible (no timestamps, no randomness).
* list/get (REQ-KNOW-003): the shared retrieval function the CLI ``knowledge``
  command and the MCP ``get_knowledge`` tool both call — epic id → epic text plus
  domain text; no id → the list of available files. An unknown id returns a clean
  empty result naming the available files, never an error.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

KNOWLEDGE_DIRNAME = "knowledge"
DOMAIN_FILENAME = "domain.md"

# The section headings every seeded file and the domain.md starter share, so the
# dev lead reviewing one recognizes the shape of the other (REQ-KNOW-002.A1,
# REQ-KNOW-004.A1). Kept as data so the seed and the starter never drift.
_PLACEHOLDER_SECTIONS = [
    ("Domain terms",
     "the vocabulary this domain uses — acronyms, entities, and what they mean, "
     "so the agent speaks the team's language rather than generic PM-speak"),
    ("Intake questions",
     "what the agent should ask a reporter about *this* domain specifically, "
     "beyond the template's required fields"),
    ("Known failure patterns",
     "the recurring bugs, regressions, and failure modes worth probing for when "
     "an observation or defect lands against this epic"),
]


# --- seed model ------------------------------------------------------------

@dataclass
class KnowledgeSeed:
    """The structure extraction a single epic's first-draft file is built from.

    Populated by onboarding from imported Jira content (REQ-KNOW-002.A1); holds
    only what the import already knows, never a model's output.
    """

    epic_id: str
    title: str
    description: str = ""
    story_titles: list[str] = field(default_factory=list)


# --- ADF → plain text ------------------------------------------------------

# Block-level ADF nodes we terminate with a newline when flattening so the
# extracted text keeps paragraph/heading/list-item boundaries.
_ADF_BLOCK_TYPES = {
    "paragraph", "heading", "listItem", "blockquote", "codeBlock", "rule",
}


def _walk_adf(node: object, out: list[str]) -> None:
    if not isinstance(node, dict):
        return
    node_type = node.get("type")
    if node_type == "text":
        out.append(str(node.get("text", "")))
        return
    if node_type == "hardBreak":
        out.append("\n")
        return
    for child in node.get("content", []) or []:
        _walk_adf(child, out)
    if node_type in _ADF_BLOCK_TYPES:
        out.append("\n")


def flatten_adf(value: object) -> str:
    """Flatten a Jira description (ADF dict or plain string) to plain text.

    Jira Cloud returns issue descriptions as ADF (a JSON document); older APIs
    return a string. Seeding only needs human-readable prose, so this is a lossy
    flattening — text nodes joined with block boundaries preserved — never a
    faithful ADF round-trip. Absent/empty input yields an empty string.

    This touches only the *seed* text; the imported-type description-preservation
    contract in ``payload.py`` is unrelated and untouched.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""
    out: list[str] = []
    _walk_adf(value, out)
    lines = [line.rstrip() for line in "".join(out).splitlines()]
    # Collapse runs of blank lines to a single blank so paragraph spacing is
    # stable regardless of ADF nesting (keeps seeding deterministic).
    cleaned: list[str] = []
    for line in lines:
        if not line and (not cleaned or not cleaned[-1]):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


# --- resolve / read (REQ-KNOW-001) -----------------------------------------

def knowledge_dir(root: Union[str, Path]) -> Path:
    """The ``knowledge/`` directory for a project — resolved, not created."""
    return Path(root) / KNOWLEDGE_DIRNAME


def epic_knowledge_path(root: Union[str, Path], epic_id: str) -> Path:
    """The single location an epic's knowledge resolves from (REQ-KNOW-001.A1)."""
    return knowledge_dir(root) / f"{epic_id}.md"


def domain_knowledge_path(root: Union[str, Path]) -> Path:
    """The single location project-wide knowledge resolves from (REQ-KNOW-001.A1)."""
    return knowledge_dir(root) / DOMAIN_FILENAME


def _read_text(path: Path) -> Optional[str]:
    """The file's plain-text content, or ``None`` when it does not exist.

    @implements REQ-KNOW-001 — a missing directory or file is not an error (A2);
    content is read as plain markdown with no schema (A3).
    """
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        return None


def read_epic_knowledge(root: Union[str, Path], epic_id: str) -> str:
    """Epic ``epic_id``'s knowledge text, or ``""`` when absent (REQ-KNOW-001)."""
    return _read_text(epic_knowledge_path(root, epic_id)) or ""


def read_domain_knowledge(root: Union[str, Path]) -> str:
    """Project-wide knowledge text, or ``""`` when absent (REQ-KNOW-001)."""
    return _read_text(domain_knowledge_path(root)) or ""


def list_knowledge(root: Union[str, Path]) -> list[str]:
    """The epic ids that have a ``knowledge/<epic-id>.md`` file, sorted.

    @implements REQ-KNOW-001 — a missing ``knowledge/`` directory yields an empty
    list (A2). ``domain.md`` is project-wide, not an epic file, so it is excluded.
    """
    directory = knowledge_dir(root)
    if not directory.is_dir():
        return []
    ids = [
        path.stem
        for path in directory.glob("*.md")
        if path.name != DOMAIN_FILENAME and path.is_file()
    ]
    return sorted(ids)


# --- get (REQ-KNOW-003) — the shared retrieval engine ----------------------

def get_knowledge(root: Union[str, Path],
                  epic_id: Optional[str] = None) -> dict:
    """The retrieval both front doors drive (REQ-KNOW-003).

    @implements REQ-KNOW-003

    With no ``epic_id`` returns the list of available knowledge files (A1/A2);
    with one, returns that epic's knowledge text plus the project-wide domain
    text (A1/A2). An unknown epic id is not an error — the result is empty and
    names the available files (A3). Same engine, same result, on both doors.
    """
    available = list_knowledge(root)
    if epic_id is None:
        return {
            "epic_id": None,
            "found": False,
            "epic": None,
            "domain": None,
            "available": available,
        }
    path = epic_knowledge_path(root, epic_id)
    epic_text = _read_text(path)
    return {
        "epic_id": epic_id,
        "found": epic_text is not None,
        "epic": epic_text or "",
        "domain": read_domain_knowledge(root),
        "available": available,
    }


def format_knowledge(result: dict) -> str:
    """Render a :func:`get_knowledge` result for the terminal (REQ-KNOW-003.A1).

    @implements REQ-KNOW-003

    List mode prints the available epic ids; show mode prints the epic's content
    combined with ``domain.md`` when present, clearly separated. An unknown id
    prints a clean message naming the available files rather than erroring (A3).
    """
    available = result.get("available") or []

    if result["epic_id"] is None:
        if not available:
            return ("No knowledge files yet. Run `taskship onboard <KEY>` to seed "
                    "them from Jira, or add knowledge/<epic-id>.md by hand.")
        return "\n".join(["Knowledge files:", *(f"  · {eid}" for eid in available)])

    if not result["found"]:
        lines = [f"No knowledge file for epic '{result['epic_id']}' "
                 f"(expected knowledge/{result['epic_id']}.md)."]
        if available:
            lines.append("Available knowledge files:")
            lines.extend(f"  · {eid}" for eid in available)
        else:
            lines.append("No knowledge files exist yet.")
        return "\n".join(lines)

    lines = [f"# Knowledge — {result['epic_id']}", "", result["epic"].rstrip()]
    if result["domain"].strip():
        lines += [
            "",
            "=" * 68,
            "# Project-wide domain knowledge (knowledge/domain.md)",
            "",
            result["domain"].rstrip(),
        ]
    return "\n".join(lines)


# --- seed (REQ-KNOW-002) ---------------------------------------------------

def render_seed(seed: KnowledgeSeed) -> str:
    """Render one epic's first-draft knowledge file (REQ-KNOW-002.A1).

    @implements REQ-KNOW-002

    Deterministic — the same seed always yields byte-identical output, with no
    timestamps or randomness (A3), so two onboards of the same content produce
    identical files. Carries the epic's title and description text, its story
    inventory, and empty placeholder sections for the curator to fill in.
    """
    lines = [f"# {seed.title}", ""]

    lines += ["## Epic description", ""]
    description = (seed.description or "").strip()
    lines.append(description if description
                 else "_No description was imported from Jira. Fill this in._")

    lines += ["", "## Stories", ""]
    if seed.story_titles:
        lines += [f"- {title}" for title in seed.story_titles]
    else:
        lines.append("_No stories were imported under this epic._")

    for heading, prompt in _PLACEHOLDER_SECTIONS:
        lines += ["", f"## {heading}", "", f"<!-- {prompt}. -->"]

    lines.append("")  # trailing newline
    return "\n".join(lines)


@dataclass
class SeedReport:
    """What seeding did, for the onboard summary (REQ-KNOW-002.A4)."""

    written: list[str] = field(default_factory=list)   # epic ids written
    skipped: list[str] = field(default_factory=list)   # epic ids left untouched


def seed_knowledge(root: Union[str, Path],
                   seeds: list[KnowledgeSeed]) -> SeedReport:
    """Write a first-draft ``knowledge/<epic-id>.md`` per seed (REQ-KNOW-002).

    @implements REQ-KNOW-002

    Never overwrites: an existing file is left byte-identical and reported as
    skipped (A2). Deterministic and model-free (A3). The caller invokes this only
    after a successful import, so it shares the plan's atomicity — a failed
    onboard writes no knowledge files (A4).
    """
    report = SeedReport()
    if not seeds:
        return report
    directory = knowledge_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    for seed in seeds:
        path = directory / f"{seed.epic_id}.md"
        if path.exists():
            report.skipped.append(seed.epic_id)
            continue
        path.write_text(render_seed(seed), encoding="utf-8")
        report.written.append(seed.epic_id)
    return report


# --- init scaffold (REQ-KNOW-004) ------------------------------------------

def _domain_starter() -> str:
    """The ``knowledge/domain.md`` starter ``taskship init`` writes.

    @implements REQ-KNOW-004 — explains the one-file-per-epic convention and
    carries placeholder sections matching the seeded shape (A1).
    """
    lines = [
        "# Domain knowledge",
        "",
        "Curated domain context the TaskShip agent reads when it interviews a",
        "reporter, splits an epic, or facilitates a ceremony. Plain markdown —",
        "there is no schema, no index, no store; the agent just reads these files.",
        "",
        "## Convention",
        "",
        "- One file per epic: `knowledge/<epic-id>.md` (the epic id from",
        "  `plan.yaml`). `taskship onboard` seeds a first draft per imported epic;",
        "  curate them by hand thereafter.",
        "- This file, `knowledge/domain.md`, holds project-wide knowledge that",
        "  applies across every epic.",
        "- Each file helps the agent with the same sections a seeded epic file has",
        "  (below). Fill them in; empty sections are fine and are simply ignored.",
    ]
    for heading, prompt in _PLACEHOLDER_SECTIONS:
        lines += ["", f"## {heading}", "", f"<!-- {prompt}. -->"]
    lines.append("")
    return "\n".join(lines)


def scaffold_knowledge(root: Union[str, Path]) -> Path:
    """Create ``knowledge/domain.md`` if absent; return its path (REQ-KNOW-004).

    @implements REQ-KNOW-004

    Idempotent: an existing ``domain.md`` (or any epic file) is never overwritten
    (A2).
    """
    directory = knowledge_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    domain = directory / DOMAIN_FILENAME
    if not domain.exists():
        domain.write_text(_domain_starter(), encoding="utf-8")
    return domain
