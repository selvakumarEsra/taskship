"""Jira client construction shared by the CLI and MCP front doors.

Keeps credential wiring in one place so both front doors build the same client
(or the same read-only offline stand-in for a dry-run).
"""
from __future__ import annotations

import os
from typing import Optional


class OfflineClient:
    """Read-only stand-in for a dry-run: knows of no existing issues."""

    def search_by_external_id(self, external_id: str) -> Optional[str]:
        return None


class MissingCredentials(Exception):
    """Jira credentials were required but not fully configured."""


def build_client(project: str):
    """Construct a real Jira client from ``JIRA_BASE_URL/EMAIL/TOKEN`` env vars."""
    from .jira import JiraClient

    cfg = {
        "base_url": os.environ.get("JIRA_BASE_URL"),
        "email": os.environ.get("JIRA_EMAIL"),
        "token": os.environ.get("JIRA_TOKEN"),
    }
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        raise MissingCredentials(
            "missing Jira credentials: "
            + ", ".join(f"JIRA_{k.upper()}" for k in missing)
        )
    return JiraClient(
        cfg["base_url"], cfg["email"], cfg["token"], project,
        sprint_field=os.environ.get("JIRA_SPRINT_FIELD"),  # e.g. customfield_10020
    )
