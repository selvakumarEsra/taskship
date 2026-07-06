"""Shared test doubles."""


class FakeJira:
    """In-memory Jira stand-in recording create/update calls (REQ-TS-005+)."""

    def __init__(self, project="CHK"):
        self.project = project
        self._counter = 100
        self.issues = {}          # key -> {"payload", "parent", "labels"}
        self.create_calls = []    # (external_id, parent_key)
        self.update_calls = []    # (key, changed_fields)
        self.label_calls = []     # (key, label)
        self.external_index = {}  # external_id -> key (simulates label search)
        self.board = {}           # key -> live {status, assignee, story_points}
        self.current = {}         # key -> current managed fields (hand-edit sim)

    def create(self, payload, parent_key):
        self._counter += 1
        key = f"{self.project}-{self._counter}"
        self.create_calls.append((payload.external_id, parent_key))
        self.issues[key] = {
            "payload": payload, "parent": parent_key, "labels": list(payload.labels)
        }
        self.external_index[payload.external_id] = key
        return key

    def update(self, key, changed_fields):
        self.update_calls.append((key, changed_fields))
        self.issues.setdefault(key, {})["patched"] = changed_fields

    def add_label(self, key, label):
        self.label_calls.append((key, label))
        self.issues.setdefault(key, {"labels": []})
        self.issues[key].setdefault("labels", []).append(label)

    def search_by_external_id(self, external_id):
        return self.external_index.get(external_id)

    def get_board_status(self, keys):
        return {k: self.board[k] for k in keys if k in self.board}

    def get_current_fields(self, key):
        return dict(self.current.get(key, {}))
