# Path: tests/test_unit.py
# Description: Unit tests for OAuth PKCE, the quota probe's transient-429 retry, the streaming usage accumulator,
#              and non-streaming usage parsing.

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from app.utils import oauth
from app.utils.usage import (
    StreamUsageAccumulator,
    reasoning_level_from_request,
    usage_from_json,
)


def test_pkce_and_authorize_url():
    verifier, challenge = oauth.generate_pkce()
    assert verifier and challenge and verifier != challenge

    url = oauth.build_authorize_url(verifier, challenge)
    assert url.startswith(oauth.config.OAUTH_AUTHORIZE_URL)
    assert "code_challenge_method=S256" in url
    assert f"state={verifier}" in url


@respx.mock
def test_fetch_usage_retries_transient_429_then_succeeds(monkeypatch):
    # The upstream usage endpoint rate-limits aggressively; its 429s are transient (inference still works), so a
    # couple of stale 429s before a 200 must be absorbed silently rather than surfaced as a probe failure.
    monkeypatch.setattr(oauth.time, "sleep", lambda _seconds: None)
    # The upstream reports `utilization` on a 0..100 percent scale (e.g. 7.0 == 7%), normalized to a 0..1 fraction.
    route = respx.get(oauth.config.OAUTH_USAGE_URL).mock(
        side_effect=[
            httpx.Response(429, json={}),
            httpx.Response(429, json={}),
            httpx.Response(200, json={"five_hour": {"utilization": 7.0}, "seven_day": {"utilization": 51.0}}),
        ]
    )

    usage = oauth.fetch_usage("access-token")

    assert route.call_count == 3
    assert usage["five_hour"]["utilization"] == pytest.approx(0.07)
    assert usage["seven_day"]["utilization"] == pytest.approx(0.51)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0.0, 0.0),
        (1.0, 0.01),  # 1% -- the boundary that the old `> 1.0` heuristic mis-read as 100%
        (24.0, 0.24),
        (97.0, 0.97),
        (100.0, 1.0),
        (150.0, 1.0),  # clamped
    ],
)
def test_normalize_bucket_treats_utilization_as_percentage(raw, expected):
    assert oauth._normalize_bucket({"utilization": raw})["utilization"] == pytest.approx(expected)


def test_normalize_bucket_used_percentage_fallback():
    assert oauth._normalize_bucket({"used_percentage": 42.0})["utilization"] == pytest.approx(0.42)


def test_normalize_bucket_identifies_rolling_cold_five_hour_placeholder():
    observed_at = datetime(2030, 1, 1, tzinfo=timezone.utc)
    result = oauth._normalize_bucket(
        {
            "utilization": 0.0,
            "resets_at": (observed_at + timedelta(hours=5)).isoformat(),
        },
        window_seconds=oauth.FIVE_HOUR_WINDOW_SECONDS,
        observed_at=observed_at,
    )

    assert result["is_cold"] is True
    assert result["reset_after_seconds"] == pytest.approx(18_000)


@respx.mock
def test_fetch_usage_raises_after_persistent_429(monkeypatch):
    # If every retry is rate-limited the probe still raises, so the caller can report it -- but only after retrying.
    monkeypatch.setattr(oauth.time, "sleep", lambda _seconds: None)
    route = respx.get(oauth.config.OAUTH_USAGE_URL).mock(return_value=httpx.Response(429, json={}))

    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        oauth.fetch_usage("access-token")

    assert excinfo.value.response.status_code == 429
    assert route.call_count > 1


def test_stream_accumulator_extracts_final_tokens():
    acc = StreamUsageAccumulator()
    acc.feed(b'data: {"type":"message_start","message":{"model":"claude-sonnet-4-6","usage":{"input_tokens":20,"cache_read_input_tokens":3}}}\n\n')
    acc.feed(b'data: {"type":"message_delta","usage":{"output_tokens":42}}\n\n')
    acc.feed(b"data: [DONE]\n\n")

    result = acc.result()
    assert result.model == "claude-sonnet-4-6"
    assert result.input_tokens == 20
    assert result.cache_read_input_tokens == 3
    assert result.output_tokens == 42


def test_usage_from_messages_response():
    usage = usage_from_json({"model": "m", "usage": {"input_tokens": 7, "output_tokens": 9}})
    assert usage.model == "m"
    assert usage.input_tokens == 7
    assert usage.output_tokens == 9


def test_usage_from_count_tokens_response():
    # count_tokens replies with a bare top-level input_tokens (no "usage" wrapper); it must still be attributed.
    usage = usage_from_json({"input_tokens": 12})
    assert usage.input_tokens == 12
    assert usage.output_tokens == 0


def test_reasoning_level_from_claude_request():
    assert (
        reasoning_level_from_request(
            {
                "thinking": {"type": "adaptive"},
                "output_config": {"effort": "HIGH"},
            }
        )
        == "high"
    )
    assert reasoning_level_from_request({"thinking": {"type": "enabled"}}) == "enabled"
    assert reasoning_level_from_request({"model": "claude-sonnet-4-6"}) is None
