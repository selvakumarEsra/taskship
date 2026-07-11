"""Jira Cloud REST v3 client (REQ-TS-006 / 008 / 009).

Implements the ``JiraClient`` protocol the reconciler depends on against a
company-managed Jira Cloud project. Auth is HTTP Basic with an account email +
API token (v0 decision of record). Issue type/subtype is encoded as labels
(``taskship:type:*`` / ``taskship:subtype:*``) and every issue carries a
``taskship:<external-id>`` watermark so a lost state file can be recovered via
JQL (REQ-TS-006).

All requests go through :meth:`_request`, which is rate-limit-aware and retries
transient failures with backoff (REQ-TS-009).
"""
from __future__ import annotations

import time
from typing import Callable, Optional

import httpx

from .payload import NodePayload, watermark_label

# Transient statuses worth retrying (429 throttle + 5xx server errors).
_RETRYABLE = {429, 500, 502, 503, 504}


class JiraError(Exception):
    """A Jira request failed (non-retryable, or retries exhausted)."""


class RateLimitExceeded(JiraError):
    """Retry ceiling hit for a throttled/transient request (REQ-TS-009)."""


def _retry_after(resp: httpx.Response, attempt: int, backoff_base: float) -> float:
    """Delay before the next attempt: honour Retry-After, else exponential."""
    retry_after = resp.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return float(retry_after)
        except ValueError:
            pass
    return backoff_base * (2 ** (attempt - 1))


def request_with_retry(
    send: Callable[[], httpx.Response],
    *,
    describe: str,
    max_attempts: int,
    backoff_base: float,
    sleep: Callable[[float], None],
) -> httpx.Response:
    """Call ``send`` with bounded, rate-limit-aware retry.

    @implements REQ-TS-009

    Retries transient statuses (429 + 5xx). A 429 honours ``Retry-After``; other
    retryable statuses back off exponentially. A non-retryable ``>=400`` fails
    immediately with :class:`JiraError`. After ``max_attempts`` transient
    failures the call raises :class:`RateLimitExceeded` naming the last status,
    so the sync stops cleanly rather than hanging.
    """
    last_status: Optional[int] = None
    for attempt in range(1, max_attempts + 1):
        resp = send()
        if resp.status_code not in _RETRYABLE:
            if resp.status_code >= 400:
                raise JiraError(f"{describe} failed: {resp.status_code} {resp.text}")
            return resp
        last_status = resp.status_code
        if attempt == max_attempts:
            break
        sleep(_retry_after(resp, attempt, backoff_base))
    raise RateLimitExceeded(
        f"{describe} still failing after {max_attempts} attempts "
        f"(last status {last_status})"
    )


class JiraClient:
    """Idempotent-friendly Jira Cloud client used by :func:`reconcile`."""

    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        project_key: str,
        *,
        sprint_field: Optional[str] = None,
        max_attempts: int = 5,
        backoff_base: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
        client: Optional[httpx.Client] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.project_key = project_key
        # Instance-specific Sprint custom field id (e.g. "customfield_10020");
        # sprint sync is a no-op when unconfigured (REQ-DEL-002).
        self.sprint_field = sprint_field
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base
        self._sleep = sleep
        self._account_cache: dict[str, str] = {}
        self._sprint_cache: dict[str, int] = {}
        self._sprint_field_discovered = False
        self._client = client or httpx.Client(
            base_url=self.base_url, auth=(email, api_token),
            headers={"Accept": "application/json"}, timeout=30.0,
        )

    # --- REQ-TS-009: rate-limit-aware request with bounded backoff ---------

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Issue a request via the shared rate-limit-aware retry policy."""
        return request_with_retry(
            lambda: self._client.request(method, path, **kwargs),
            describe=f"{method} {path}",
            max_attempts=self.max_attempts,
            backoff_base=self.backoff_base,
            sleep=self._sleep,
        )

    # --- REQ-TS-005: create / update --------------------------------------

    def create(self, payload: NodePayload, parent_key: Optional[str]) -> str:
        fields = {
            "project": {"key": self.project_key},
            "summary": payload.summary,
            "issuetype": {"name": payload.issue_type},
            "labels": payload.labels,
        }
        if payload.description is not None:
            fields["description"] = payload.description
        if parent_key is not None:
            fields["parent"] = {"key": parent_key}
        if payload.assignee is not None:
            fields["assignee"] = {"accountId": self._account_id(payload.assignee)}
        if payload.sprint is not None and self._sprint_field_id():
            fields[self._sprint_field_id()] = self._sprint_id(payload.sprint)
        resp = self._request("POST", "/rest/api/3/issue", json={"fields": fields})
        return resp.json()["key"]

    def update(self, key: str, changed_fields: dict) -> None:
        fields = {}
        if "summary" in changed_fields:
            fields["summary"] = changed_fields["summary"]
        if "labels" in changed_fields:
            fields["labels"] = changed_fields["labels"]
        if "description" in changed_fields:
            fields["description"] = changed_fields["description"]
        if "assignee" in changed_fields:
            fields["assignee"] = {"accountId": self._account_id(changed_fields["assignee"])}
        if "sprint" in changed_fields and self._sprint_field_id():
            fields[self._sprint_field_id()] = self._sprint_id(changed_fields["sprint"])
        if fields:
            self._request("PUT", f"/rest/api/3/issue/{key}", json={"fields": fields})

    # --- REQ-DEL-002: sprint field discovery + name → id resolution -------

    def _sprint_field_id(self) -> Optional[str]:
        """The Sprint custom field id — configured, else discovered once.

        Jira Cloud has no fixed id for the Sprint field; when ``sprint_field``
        wasn't configured, look it up from ``/rest/api/3/field`` by schema.
        Returns ``None`` (sprint sync disabled) when the site has no Sprint field.
        """
        if self.sprint_field or self._sprint_field_discovered:
            return self.sprint_field
        self._sprint_field_discovered = True
        resp = self._request("GET", "/rest/api/3/field")
        for f in resp.json():
            if f.get("schema", {}).get("custom", "").endswith(":gh-sprint"):
                self.sprint_field = f["id"]
                break
        return self.sprint_field

    def _sprint_id(self, sprint: object) -> int:
        """Resolve an authored sprint (name or id) to Jira's numeric sprint id.

        The Sprint field rejects strings ("The Sprint (id) must be a number" —
        verified against Jira Cloud), so a name like "Sprint 12" is resolved via
        the Agile API: boards for the project → sprints by name. Raises
        :class:`JiraError` naming the sprint when nothing matches, so the
        reconciler records a per-node error and continues.
        """
        text = str(sprint)
        if text.isdigit():
            return int(text)
        if text in self._sprint_cache:
            return self._sprint_cache[text]
        boards = self._request(
            "GET", "/rest/agile/1.0/board",
            params={"projectKeyOrId": self.project_key},
        ).json().get("values", [])
        for board in boards:
            start = 0
            while True:
                page = self._request(
                    "GET", f"/rest/agile/1.0/board/{board['id']}/sprint",
                    params={"startAt": start, "maxResults": 50},
                ).json()
                for s in page.get("values", []):
                    if s.get("name") == text:
                        self._sprint_cache[text] = s["id"]
                        return s["id"]
                if page.get("isLast", True):
                    break
                start += len(page.get("values", []))
        raise JiraError(
            f"no sprint named '{text}' on any board of project {self.project_key}"
        )

    # --- REQ-DEL-001: resolve an authored assignee to a Jira accountId ----

    def _account_id(self, assignee: str) -> str:
        """Resolve an email to a Jira accountId; pass an accountId through.

        @implements REQ-DEL-001

        Raises :class:`JiraError` naming the assignee when no user matches, so
        the reconciler records it as a per-node error and continues.
        """
        if "@" not in assignee:
            return assignee  # already an accountId
        if assignee in self._account_cache:
            return self._account_cache[assignee]
        resp = self._request(
            "GET", "/rest/api/3/user/search", params={"query": assignee},
        )
        users = resp.json()
        if not users:
            raise JiraError(f"no Jira user matches assignee '{assignee}'")
        account_id = users[0]["accountId"]
        self._account_cache[assignee] = account_id
        return account_id

    # --- REQ-TS-008: orphan flagging --------------------------------------

    def add_label(self, key: str, label: str) -> None:
        """Attach a label without touching others (used for orphan flagging)."""
        self._request(
            "PUT", f"/rest/api/3/issue/{key}",
            json={"update": {"labels": [{"add": label}]}},
        )

    # --- REQ-TS-006: external-id recovery via watermark search ------------

    def search_by_external_id(self, external_id: str) -> Optional[str]:
        """Recover a node's Jira key from its ``taskship:<id>`` watermark label.

        @implements REQ-TS-006
        """
        jql = f'project = "{self.project_key}" AND labels = "{watermark_label(external_id)}"'
        resp = self._request(
            "POST", "/rest/api/3/search/jql",
            json={"jql": jql, "maxResults": 1, "fields": ["key"]},
        )
        issues = resp.json().get("issues", [])
        return issues[0]["key"] if issues else None

    # --- REQ-TS-011: read current managed fields (conflict detection) -----

    def get_current_fields(self, key: str) -> dict:
        """Read the managed fields' current board values for conflict checks.

        @implements REQ-TS-011
        """
        resp = self._request(
            "GET", f"/rest/api/3/issue/{key}",
            params={"fields": "summary,labels,description"},
        )
        f = resp.json().get("fields", {})
        out: dict = {}
        if "summary" in f:
            out["summary"] = f["summary"]
        if "labels" in f:
            out["labels"] = sorted(f["labels"])
        if "description" in f:
            out["description"] = f["description"]
        return out

    # --- REQ-ONBOARD-001: read the whole project for onboarding -----------

    def search_project_issues(self) -> list[dict]:
        """Every epic/story/task in the project, paginated (REQ-ONBOARD-001).

        @implements REQ-ONBOARD-001

        Walks the token-paginated ``/rest/api/3/search/jql`` endpoint until the
        last page, so a project larger than Jira's page-size limit is imported
        whole. Requests only the fields onboarding needs — summary, issue type,
        parent, labels, status (for done-filtering and noise flags), and
        description (presence only, never rewritten for imported tasks).
        """
        jql = f'project = "{self.project_key}" ORDER BY created ASC'
        fields = ["summary", "issuetype", "parent", "labels", "status", "description"]
        issues: list[dict] = []
        next_token: Optional[str] = None
        while True:
            body: dict = {"jql": jql, "maxResults": 100, "fields": fields}
            if next_token is not None:
                body["nextPageToken"] = next_token
            resp = self._request("POST", "/rest/api/3/search/jql", json=body)
            data = resp.json()
            issues.extend(data.get("issues", []))
            next_token = data.get("nextPageToken")
            if not next_token or data.get("isLast", False):
                break
        return issues

    # --- REQ-TS-010: reverse sync — live board state ----------------------

    def get_board_status(
        self, keys: list[str], story_points_field: Optional[str] = None
    ) -> dict[str, dict]:
        """Read status/assignee/story points for the given issue keys.

        @implements REQ-TS-010

        ``story_points_field`` is the instance-specific custom field id (Jira
        Cloud has no standard one); omitted → story points report ``None``.
        """
        if not keys:
            return {}
        fields = ["status", "assignee"]
        if story_points_field:
            fields.append(story_points_field)
        key_list = ", ".join(f'"{k}"' for k in keys)
        resp = self._request(
            "POST", "/rest/api/3/search/jql",
            json={"jql": f"key in ({key_list})", "maxResults": len(keys),
                  "fields": fields},
        )
        out: dict[str, dict] = {}
        for issue in resp.json().get("issues", []):
            f = issue.get("fields", {})
            status = (f.get("status") or {}).get("name")
            assignee = (f.get("assignee") or {}).get("displayName")
            sp = f.get(story_points_field) if story_points_field else None
            out[issue["key"]] = {
                "status": status, "assignee": assignee, "story_points": sp
            }
        return out
