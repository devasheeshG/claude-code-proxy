"""CRUD, secret handling, spend caps, and routing tests for Anthropic-compatible fallbacks."""

import json

import httpx
import respx

from app.utils import anthropic_fallbacks, crypto
from app.utils.postgres import AnthropicFallbackDb, UsageRecordDb
from app.utils.postgres.base import SessionFactory


def _create(client, admin_headers, **overrides):
    payload = {
        "label": "Reserve",
        "base_url": "https://fallback.example/",
        "api_key": "sk-ant-test-secret-value",
        "monthly_spend_limit_usd": 10.0,
        "priority": 2,
        **overrides,
    }
    response = client.post("/api/v1/fallbacks", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["fallback"]


def _message(model="claude-haiku-4-5", input_tokens=10, output_tokens=5):
    return {
        "id": "msg_fallback",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


def test_fallback_secret_is_write_only_and_lifecycle_is_managed(client, admin_headers):
    created = _create(client, admin_headers)
    rendered = json.dumps(created)
    assert "sk-ant-test-secret-value" not in rendered
    assert created["key_hint"] == "••••alue"
    assert created["base_url"] == "https://fallback.example"
    assert created["status"] == "ACTIVE"

    with SessionFactory() as db:
        stored = db.get(AnthropicFallbackDb, created["id"])
        assert stored.api_key_enc != "sk-ant-test-secret-value"
        assert crypto.decrypt(stored.api_key_enc) == "sk-ant-test-secret-value"

    disabled = client.post(f"/api/v1/fallbacks/{created['id']}/disable", headers=admin_headers)
    assert disabled.status_code == 200
    assert disabled.json()["fallback"]["status"] == "DISABLED"

    enabled = client.post(f"/api/v1/fallbacks/{created['id']}/enable", headers=admin_headers)
    assert enabled.status_code == 200
    assert enabled.json()["fallback"]["status"] == "ACTIVE"

    updated = client.put(
        f"/api/v1/fallbacks/{created['id']}",
        headers=admin_headers,
        json={"label": "Renamed", "clear_monthly_spend_limit": True, "priority": 1},
    )
    assert updated.status_code == 200
    assert updated.json()["fallback"]["monthly_spend_limit_usd"] is None
    with SessionFactory() as db:
        stored = db.get(AnthropicFallbackDb, created["id"])
        assert anthropic_fallbacks.api_key(stored) == "sk-ant-test-secret-value"


def test_duplicate_fallback_credential_and_base_url_is_rejected(client, admin_headers):
    _create(client, admin_headers)
    response = client.post(
        "/api/v1/fallbacks",
        headers=admin_headers,
        json={
            "label": "Duplicate",
            "base_url": "https://fallback.example",
            "api_key": "sk-ant-test-secret-value",
            "priority": 1,
        },
    )
    assert response.status_code == 409


def test_fallback_endpoint_accepts_origin_or_v1_root():
    class Provider:
        pass

    origin = Provider()
    origin.base_url = "https://api.example"
    v1_root = Provider()
    v1_root.base_url = "https://api.example/v1"
    assert anthropic_fallbacks.endpoint(origin, "/v1/messages") == "https://api.example/v1/messages"
    assert anthropic_fallbacks.endpoint(v1_root, "/v1/messages") == "https://api.example/v1/messages"


@respx.mock
def test_proxy_uses_fallback_only_when_subscription_pool_cannot_serve(client, admin_headers, make_user):
    fallback = _create(client, admin_headers, monthly_spend_limit_usd=1.0)
    route = respx.post("https://fallback.example/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json=_message(),
            headers={"content-type": "application/json", "request-id": "fallback-request"},
        )
    )
    key = make_user("fallback-user", fallback_enabled=True)

    response = client.post(
        "/api/v1/messages",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "claude-haiku-4-5", "max_tokens": 8, "messages": []},
    )

    assert response.status_code == 200, response.text
    assert route.calls[0].request.headers["x-api-key"] == "sk-ant-test-secret-value"
    assert "authorization" not in route.calls[0].request.headers
    assert "oauth-2025-04-20" not in route.calls[0].request.headers.get("anthropic-beta", "")
    with SessionFactory() as db:
        record = db.query(UsageRecordDb).one()
        assert str(record.fallback_provider_id) == fallback["id"]
        assert record.account_id is None
        assert record.billed_cost_usd > 0


@respx.mock
def test_exhausted_fallback_spend_cap_prevents_more_requests(client, admin_headers, make_user):
    fallback = _create(client, admin_headers, monthly_spend_limit_usd=0.00001)
    route = respx.post("https://fallback.example/v1/messages").mock(
        return_value=httpx.Response(200, json=_message(), headers={"content-type": "application/json"})
    )
    key = make_user("capped-user", fallback_enabled=True)
    headers = {"Authorization": f"Bearer {key}"}
    payload = {"model": "claude-haiku-4-5", "max_tokens": 8, "messages": []}

    first = client.post("/api/v1/messages", headers=headers, json=payload)
    second = client.post("/api/v1/messages", headers=headers, json=payload)

    assert first.status_code == 200
    assert second.status_code == 503
    assert route.call_count == 1
    item = next(value for value in client.get("/api/v1/fallbacks", headers=admin_headers).json()["fallbacks"] if value["id"] == fallback["id"])
    assert item["monthly_spend_usd"] > item["monthly_spend_limit_usd"]
    assert item["monthly_spend_remaining_usd"] == 0


@respx.mock
def test_fallback_supports_count_tokens_without_billing_it(client, admin_headers, make_user):
    _create(client, admin_headers)
    route = respx.post("https://fallback.example/v1/messages/count_tokens").mock(
        return_value=httpx.Response(200, json={"input_tokens": 7}, headers={"content-type": "application/json"})
    )
    key = make_user("token-counter", fallback_enabled=True)
    response = client.post(
        "/api/v1/messages/count_tokens",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "claude-haiku-4-5", "messages": []},
    )
    assert response.status_code == 200
    assert response.json() == {"input_tokens": 7}
    assert route.calls[0].request.headers["x-api-key"] == "sk-ant-test-secret-value"
    with SessionFactory() as db:
        assert db.query(UsageRecordDb).count() == 0


@respx.mock
def test_fallback_health_check_refreshes_models_without_exposing_key(client, admin_headers):
    fallback = _create(client, admin_headers)
    route = respx.get("https://fallback.example/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "claude-test", "type": "model"}]})
    )

    response = client.post(f"/api/v1/fallbacks/{fallback['id']}/test", headers=admin_headers)

    assert response.status_code == 200
    result = response.json()["fallback"]
    assert result["provider_health"] == "HEALTHY"
    assert result["model_count"] == 1
    assert "sk-ant-test-secret-value" not in response.text
    assert route.calls[0].request.headers["x-api-key"] == "sk-ant-test-secret-value"
