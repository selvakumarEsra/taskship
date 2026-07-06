"""Local sync state: ``.taskship/state.json`` (REQ-TS-005).

Maps each node's qualified id to its Jira key, an overall content hash, and a
per-field hash snapshot. The overall hash decides create/update/skip; the
per-field hashes let an update patch only the fields that actually changed
(REQ-TS-005 A3). The state file is the fast path; when it's missing, sync
recovers the mapping from Jira via the external-id watermark (REQ-TS-006).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class StateEntry:
    jira: str
    hash: str
    fields: dict[str, str] = field(default_factory=dict)


class StateStore:
    """Load/mutate/persist the id→(key, hash, field-hashes) mapping."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._entries: dict[str, StateEntry] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        for ext_id, e in raw.items():
            self._entries[ext_id] = StateEntry(
                jira=e["jira"], hash=e["hash"], fields=e.get("fields", {})
            )

    def entry(self, external_id: str) -> Optional[StateEntry]:
        return self._entries.get(external_id)

    def key(self, external_id: str) -> Optional[str]:
        e = self._entries.get(external_id)
        return e.jira if e else None

    def record(self, external_id: str, jira: str, hash_: str, fields: dict[str, str]) -> None:
        self._entries[external_id] = StateEntry(jira=jira, hash=hash_, fields=fields)

    def known_ids(self) -> set[str]:
        return set(self._entries)

    def drop(self, external_id: str) -> None:
        """Forget a node — used once an orphan is handed off to a human."""
        self._entries.pop(external_id, None)

    def save(self) -> None:
        """Persist atomically (temp + replace) so a crash never truncates state."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            ext_id: {"jira": e.jira, "hash": e.hash, "fields": e.fields}
            for ext_id, e in self._entries.items()
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)
