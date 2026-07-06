"""REQ-TS-009 — Jira calls are rate-limit-aware and retried with backoff.

A1: a 429 with Retry-After is waited out and retried; the call ultimately succeeds.
A2: retries are bounded; the ceiling raises an error naming the Jira status.
"""
import httpx
import pytest

from taskship import Plan
from taskship.jira import JiraClient, RateLimitExceeded, JiraError
from taskship.payload import build_payloads


def _client(handler, sleeps, **kw):
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://x.atlassian.net",
                        auth=("e", "t"))
    return JiraClient("https://x.atlassian.net", "e", "t", "CHK",
                      sleep=lambda s: sleeps.append(s), client=http, **kw)


def _payload():
    plan = Plan.from_mapping({
        "product": "P", "jira_project": "CHK",
        "epics": [{"id": "e", "title": "E"}],
    })
    return build_payloads(plan)[0]


def test_a1_429_with_retry_after_is_retried_then_succeeds():
    calls = {"n": 0}
    sleeps = []

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(201, json={"key": "CHK-101"})

    client = _client(handler, sleeps)
    key = client.create(_payload(), None)

    assert key == "CHK-101"       # ultimately succeeds, no operator intervention
    assert calls["n"] == 2        # one retry
    assert sleeps == [2.0]        # honoured Retry-After


def test_a2_retries_bounded_then_raises_naming_status():
    calls = {"n": 0}
    sleeps = []

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503)  # persistently unavailable

    client = _client(handler, sleeps, max_attempts=4, backoff_base=0.1)
    with pytest.raises(RateLimitExceeded) as exc:
        client.create(_payload(), None)

    assert calls["n"] == 4                 # bounded — exactly max_attempts
    assert len(sleeps) == 3                # slept between attempts, not after the last
    assert "503" in str(exc.value)         # names the underlying status


def test_exponential_backoff_without_retry_after():
    calls = {"n": 0}
    sleeps = []

    def handler(request):
        calls["n"] += 1
        return httpx.Response(500) if calls["n"] < 3 else httpx.Response(201, json={"key": "K"})

    client = _client(handler, sleeps, backoff_base=0.5)
    client.create(_payload(), None)
    assert sleeps == [0.5, 1.0]            # 0.5 * 2**0, 0.5 * 2**1


def test_non_retryable_4xx_fails_immediately():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(400, text="bad request")

    client = _client(handler, [])
    with pytest.raises(JiraError):
        client.create(_payload(), None)
    assert calls["n"] == 1                  # no retries on a client error
