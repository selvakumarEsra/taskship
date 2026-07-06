"""Decomposition: product brief → schema-valid plan (REQ-TS-014).

Decomposition is the last, most swappable piece: the valuable, hard-to-get-right
parts (schema, templates, idempotent sync) live elsewhere, and the plan
*generator* is a bolt-on behind a stable interface. ``decompose_brief`` takes a
brief and a generator, validates the generator's output against the plan schema,
and returns the structured tree. Invalid output is **rejected**, never silently
patched, and no plan is written. The function is pure — it makes no Jira calls.

The default generator is deterministic and dependency-free so decomposition runs
without an LLM. A real LLM generator (Claude with structured output, seeded with
the template catalog) is a drop-in replacement satisfying the same
``Generator`` contract:

    def my_llm_generator(brief: str) -> dict: ...
    decompose_brief(brief, generator=my_llm_generator)
"""
from __future__ import annotations

import re
from typing import Callable, Optional

from .model import Plan

Generator = Callable[[str], dict]


def _slugish(text: str, fallback: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return cleaned or fallback


def heuristic_generator(brief: str) -> dict:
    """A deterministic, LLM-free generator that yields a valid starter plan.

    @implements REQ-TS-014

    Splits the brief into a product name and a first capability, then emits a
    single epic → story with a ``biz-spec`` task — always schema-valid, never
    random. Intended as the runnable default and the reference shape a real LLM
    generator should produce (richer, but the same contract).
    """
    brief = brief.strip()
    # "Product: capability description" → product / capability split.
    if ":" in brief:
        product_part, capability = brief.split(":", 1)
    else:
        product_part, capability = brief, brief
    product = product_part.strip() or "New product"
    capability = capability.strip() or product

    epic_id = _slugish(product, "epic")
    return {
        "product": product,
        "jira_project": "PROJ",
        "epics": [
            {
                "id": epic_id,
                "title": product,
                "stories": [
                    {
                        "id": _slugish(capability, "story"),
                        "title": capability,
                        "tasks": [
                            {
                                "type": "biz-spec",
                                "title": f"Define requirements for {capability}",
                            }
                        ],
                    }
                ],
            }
        ],
    }


def decompose_brief(text: str, generator: Optional[Generator] = None) -> dict:
    """Decompose a brief into a schema-valid plan tree.

    @implements REQ-TS-014

    Runs the generator, validates its output against the plan schema (raising
    :class:`~taskship.model.PlanValidationError` on invalid output — no repair,
    no write), and returns the validated plan as a dict. Makes no Jira calls.
    """
    gen = generator or heuristic_generator
    raw = gen(text)
    plan = Plan.from_mapping(raw)  # rejects invalid output
    # Drop unset/default fields so the returned tree (and any plan.yaml written
    # from it) stays clean and reviewable — the schema restores defaults on load.
    return plan.model_dump(exclude_none=True, exclude_defaults=True)
