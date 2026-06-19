# Path: app/routes/proxy.py
# Description: The proxy itself -- authenticate the user, pick a pooled account (with failover), forward the
#              Anthropic-shaped request upstream, stream the response back, and record per-user token usage.
#              This route is async (unlike the admin routes) because it streams SSE responses end to end.

import asyncio
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Mapping, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app import config
from app.logger import get_logger
from app.routes.me import build_pool_status
from app.utils import (
    account_limiter,
    anthropic_fallbacks,
    events,
    notifications,
    provider_health,
    request_context,
    request_policy,
    rotation,
    security,
    usage,
    warmup,
)
from app.utils.postgres import AccountDb, AnthropicFallbackDb, ApiKeyDb, UsageRecordDb, UserDb, get_db, get_db_cm
from app.utils.thinking import thinking_level_from_request

# Get the logger
logger = get_logger()

# Get the settings
settings = config.get_settings()

router = APIRouter(tags=["Proxy"])


def _emit_event(
    request: Request,
    event_type: str,
    *,
    user_id=None,
    api_key_id=None,
    account_id=None,
    fallback_provider_id=None,
    status_code=None,
    message=None,
    metadata=None,
) -> None:
    """Persist observability without ever allowing event storage to affect routing."""
    request_id = getattr(request.state, "proxy_event_request_id", None)
    if request_id:
        context = getattr(request.state, "proxy_event_context", {})
        merged_metadata = {**context, **(metadata or {})}
        events.record_event(
            event_type,
            request_id,
            user_id=user_id,
            api_key_id=api_key_id,
            account_id=account_id,
            fallback_provider_id=fallback_provider_id,
            status_code=status_code,
            message=message,
            metadata=merged_metadata,
        )


# Request headers we must never forward upstream.
_STRIP_REQUEST_HEADERS = {
    "host",
    "content-length",
    "accept-encoding",  # force identity so we can parse the SSE stream
    "authorization",  # replaced with the account's OAuth bearer
    "x-api-key",  # OAuth uses bearer, not api-key
    "connection",
    "keep-alive",
    "transfer-encoding",
    "te",
    "trailer",
    "upgrade",
    "proxy-authorization",
    "proxy-authenticate",
}

# Response headers the ASGI server sets itself, so we must not pass them back verbatim.
_STRIP_RESPONSE_HEADERS = {"content-length", "content-encoding", "transfer-encoding", "connection", "keep-alive"}

# Provider quota headers describe the one account that was attempted.  They
# must not leak that account's private window into a pooled response; they are
# replaced below with the same aggregate values exposed by GET /me/usage.
_POOL_QUOTA_RESPONSE_HEADERS = {
    "anthropic-ratelimit-unified-5h-utilization",
    "anthropic-ratelimit-unified-5h-reset",
    "anthropic-ratelimit-unified-7d-utilization",
    "anthropic-ratelimit-unified-7d-reset",
    "anthropic-ratelimit-unified-status",
}


def _pool_quota_response_headers(db: Session, headers: Mapping[str, str]) -> Dict[str, str]:
    """Rewrite provider quota headers to match the shared-pool /me/usage snapshot."""
    response_headers = {key: value for key, value in headers.items() if key.lower() not in _POOL_QUOTA_RESPONSE_HEADERS}
    pool = build_pool_status(db)
    if pool is None:
        return response_headers

    five_hour = pool.five_hour
    if five_hour.used_pct is not None:
        response_headers["anthropic-ratelimit-unified-5h-utilization"] = f"{five_hour.used_pct:.6f}".rstrip("0").rstrip(".")
    if five_hour.next_reset_at is not None:
        response_headers["anthropic-ratelimit-unified-5h-reset"] = str(int(five_hour.next_reset_at.timestamp()))

    weekly = pool.weekly
    if weekly.used_pct is not None:
        response_headers["anthropic-ratelimit-unified-7d-utilization"] = f"{weekly.used_pct:.6f}".rstrip("0").rstrip(".")
    if weekly.next_reset_at is not None:
        response_headers["anthropic-ratelimit-unified-7d-reset"] = str(int(weekly.next_reset_at.timestamp()))
    return response_headers


def _override_model(user: Optional[UserDb], requested_model: object) -> Optional[str]:
    if not isinstance(requested_model, str):
        return requested_model if requested_model is None else str(requested_model)
    requested = requested_model.strip().lower()
    if user is None or not requested:
        return requested_model
    overrides = request_policy.decode_model_overrides(user.model_overrides_json)
    return overrides.get(requested, requested_model)


def _restore_requested_model_in_error(
    raw: bytes,
    status_code: int,
    requested_model: object,
    effective_model: object,
) -> bytes:
    """Keep a per-user upstream override private in client-visible errors."""
    if status_code < 400 or not isinstance(requested_model, str) or not isinstance(effective_model, str):
        return raw
    if not requested_model or requested_model == effective_model:
        return raw
    return re.sub(
        re.escape(effective_model).encode(),
        lambda _match: requested_model.encode(),
        raw,
        flags=re.IGNORECASE,
    )


def _build_upstream_headers(incoming, access_token: str) -> Dict[str, str]:
    """Clone the client's headers, strip auth/transport, inject the OAuth bearer and the required anthropic flags."""
    headers: Dict[str, str] = {}
    for key, value in incoming.items():
        if key.lower() not in _STRIP_REQUEST_HEADERS:
            headers[key] = value

    headers["Authorization"] = f"Bearer {access_token}"

    beta = headers.get("anthropic-beta")
    if not beta:
        headers["anthropic-beta"] = config.ANTHROPIC_BETA
    elif config.ANTHROPIC_BETA not in beta:
        headers["anthropic-beta"] = f"{beta},{config.ANTHROPIC_BETA}"

    headers.setdefault("anthropic-version", config.ANTHROPIC_VERSION)
    headers.setdefault("User-Agent", config.CLAUDE_CODE_USER_AGENT)
    return headers


def _build_fallback_headers(incoming, api_key: str) -> Dict[str, str]:
    """Build Anthropic API-key headers without subscription-only OAuth beta flags."""
    headers: Dict[str, str] = {}
    for key, value in incoming.items():
        if key.lower() not in _STRIP_REQUEST_HEADERS:
            headers[key] = value
    headers["x-api-key"] = api_key
    headers.setdefault("anthropic-version", config.ANTHROPIC_VERSION)
    headers.setdefault("User-Agent", config.CLAUDE_CODE_USER_AGENT)
    return headers


async def _is_capacity_unavailable(candidate: httpx.Response) -> bool:
    """Recognize explicit model-capacity responses that may be retried elsewhere.

    Rate-limit responses deliberately are not capacity responses.  They must
    reach the quota branch below so provider headers and ``Retry-After`` are
    persisted correctly.
    """
    if getattr(candidate, "_proxy_capacity_error", False) or candidate.extensions.get("proxy_capacity_error", False):
        return True
    if candidate.status_code not in {400, 403, 404, 409, 429, 500, 502, 503, 529}:
        return False
    body = (await candidate.aread()).decode(errors="replace").lower()
    clear_phrase = any(
        phrase in body
        for phrase in (
            "at capacity",
            "try a different model",
            "service exhausted",
            "temporarily overloaded",
        )
    )
    return clear_phrase or ("capacity" in body and "model" in body) or ("overloaded" in body and "model" in body)


class _PrefetchedResponse:
    """Small response proxy that replays bytes consumed while checking an SSE error prefix."""

    def __init__(self, response: httpx.Response, prefix: bytes, iterator, capacity_error: bool) -> None:
        self._response = response
        self._prefix = prefix
        self._iterator = iterator
        self._capacity_error = capacity_error
        self._body: Optional[bytes] = None

    @property
    def _proxy_capacity_error(self) -> bool:
        return self._capacity_error

    def __getattr__(self, name):
        return getattr(self._response, name)

    async def aclose(self) -> None:
        await self._response.aclose()

    async def aread(self) -> bytes:
        if self._body is None:
            self._body = self._prefix + b"".join([chunk async for chunk in self._iterator])
            self._prefix = b""
        return self._body

    async def aiter_bytes(self):
        if self._body is not None:
            if self._body:
                yield self._body
            return
        if self._prefix:
            yield self._prefix
            self._prefix = b""
        async for chunk in self._iterator:
            yield chunk


_CAPACITY_PHRASES = (
    "at capacity",
    "try a different model",
    "service exhausted",
    "temporarily overloaded",
)
_FAIL_MARKERS = (
    "response.failed",
    '"status":"failed"',
    '"status": "failed"',
    '"type":"error"',
    '"type": "error"',
)
_OUTPUT_DELTA_MARKERS = (
    "message_start",
    "message_delta",
    "content_block_start",
    "content_block_delta",
    "output_text.delta",
    "content_part.delta",
    "response.function_call_arguments.delta",
    "response.reasoning_summary_text.delta",
    "response.reasoning_text.delta",
)
_SUCCESS_MARKERS = ("message_stop",)


def _is_pre_output_failure(lowered: str) -> bool:
    """Return True if the lowered SSE text shows a failure with no output."""
    has_failed = any(m in lowered for m in _FAIL_MARKERS)
    has_output = any(m in lowered for m in _OUTPUT_DELTA_MARKERS)
    return has_failed and not has_output


async def _empty_aiter():
    """Yield nothing -- used as the remaining-bytes iterator for fully-read responses."""
    return
    yield  # noqa: RET504  -- makes this an async generator


async def _prepare_candidate(candidate: httpx.Response):
    """Inspect the beginning of a successful SSE response for early failures.

    The proxy must not start forwarding a stream to the client until there is
    reasonable confidence the upstream will produce output.  This function
    buffers SSE frames and keeps reading until one of three outcomes:

    1. An **output-delta** event is seen  -> the model is generating; start
       streaming (return ``capacity_error=False``).
    2. A **response.failed** / capacity phrase is seen *without* any output
       delta  -> the request failed before generating; the caller can safely
       retry on the next account (``capacity_error=True``).
    3. A safety bound is reached (64 KB or 90 s total prefetch time) without
       either signal -> treat this attempt as failed and rotate accounts.

    The original bug forwarded buffered keepalives after a prefix timeout;
    the provider could then emit a late failure/capacity event directly to the
    CLI, ending the user's run instead of triggering account failover. We now
    hold the stream until real output/completion and rotate on any pre-output
    timeout or terminal failure.
    """
    if candidate.status_code != 200:
        return candidate
    content_type = candidate.headers.get("content-type", "").lower()

    # The upstream sometimes omits the Content-Type header entirely even
    # though it sends a valid SSE stream.  Detect this by peeking at the
    # first bytes: if they start with "event:" or "data:", treat it as SSE.
    is_sse = "text/event-stream" in content_type

    if not is_sse:
        raw = await candidate.aread()
        lowered = raw.decode(errors="replace").lower()

        if raw.lstrip().startswith((b"event:", b"data:")):
            is_sse = True
        else:
            candidate.extensions["proxy_capacity_error"] = any(p in lowered for p in _CAPACITY_PHRASES) or _is_pre_output_failure(lowered)
            return candidate

    if is_sse and hasattr(candidate, "_content") and candidate._content:
        lowered = candidate._content.decode(errors="replace").lower()
        is_capacity_error = any(p in lowered for p in _CAPACITY_PHRASES) or _is_pre_output_failure(lowered)
        if is_capacity_error:
            return _PrefetchedResponse(
                candidate,
                candidate._content,
                _empty_aiter(),
                True,
            )
        return _PrefetchedResponse(
            candidate,
            candidate._content,
            _empty_aiter(),
            False,
        )

    iterator = candidate.aiter_bytes().__aiter__()
    prefix = bytearray()
    prefetch_deadline = asyncio.get_event_loop().time() + 90
    first_byte_timeout = 60

    while len(prefix) < 64 * 1024:
        elapsed = asyncio.get_event_loop().time()
        if elapsed >= prefetch_deadline:
            logger.warning("Upstream produced no output before the SSE prefetch deadline; treating as capacity unavailable")
            return _PrefetchedResponse(candidate, bytes(prefix), iterator, True)
        remaining = max(1, prefetch_deadline - elapsed)
        try:
            timeout = min(
                first_byte_timeout if not prefix else 30,
                remaining,
            )
            chunk = await asyncio.wait_for(
                iterator.__anext__(),
                timeout=timeout,
            )
        except StopAsyncIteration:
            break
        except (asyncio.TimeoutError, TimeoutError):
            logger.warning("Upstream produced no output within the SSE prefetch timeout; treating as capacity unavailable")
            return _PrefetchedResponse(candidate, bytes(prefix), iterator, True)
        prefix.extend(chunk)
        lowered = bytes(prefix).decode(errors="replace").lower()

        # Explicit capacity phrases -> always retry.
        if any(p in lowered for p in _CAPACITY_PHRASES):
            return _PrefetchedResponse(
                candidate,
                bytes(prefix),
                iterator,
                True,
            )

        has_output = any(m in lowered for m in _OUTPUT_DELTA_MARKERS)
        completed = any(m in lowered for m in _SUCCESS_MARKERS)

        # Real output is flowing -> response is healthy, start streaming.
        if has_output or completed:
            return _PrefetchedResponse(candidate, bytes(prefix), iterator, False)

        # Nothing has reached the client yet, so a terminal upstream failure is
        # safe to retry on another account. The caller applies the short cooldown
        # that prevents every concurrent request from piling onto this account.
        if _is_pre_output_failure(lowered):
            return _PrefetchedResponse(candidate, bytes(prefix), iterator, True)

    logger.warning("Upstream filled the SSE prefetch buffer without producing output; treating as capacity unavailable")
    return _PrefetchedResponse(candidate, bytes(prefix), iterator, True)


def _record_usage_safe(
    user_id: uuid.UUID,
    api_key_id: Optional[uuid.UUID],
    account_id: Optional[uuid.UUID],
    usage_obj: usage.Usage,
    status_code: Optional[int],
    request_id: Optional[str],
    fallback_provider_id: Optional[uuid.UUID] = None,
) -> None:
    """Record usage in its own short-lived session; usage accounting must never break the proxied response."""
    try:
        with get_db_cm() as db:
            usage.record_usage(
                db,
                user_id,
                api_key_id,
                account_id,
                usage_obj,
                status_code,
                request_id,
                fallback_provider_id,
            )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to record proxied token usage")


def _set_archive_metadata(request: Request, **fields: object) -> None:
    """Attach non-sensitive routing/usage data for request-scoped diagnostics."""
    metadata = getattr(request.state, "archive_metadata", None)
    if isinstance(metadata, dict):
        metadata.update({key: value for key, value in fields.items() if value is not None})


def _archive_usage(request: Request, usage_obj: usage.Usage) -> None:
    _set_archive_metadata(
        request,
        usage={
            "model": usage_obj.model,
            "input_tokens": usage_obj.input_tokens,
            "output_tokens": usage_obj.output_tokens,
            "cache_creation_input_tokens": usage_obj.cache_creation_input_tokens,
            "cache_read_input_tokens": usage_obj.cache_read_input_tokens,
            "cache_creation_5m_input_tokens": usage_obj.cache_creation_5m_input_tokens,
            "cache_creation_1h_input_tokens": usage_obj.cache_creation_1h_input_tokens,
            "reasoning_level": usage_obj.reasoning_level,
        },
    )


async def _send_with_account_limit(client, method, url, headers, content, account, priority):
    lease = account_limiter.try_acquire(account.id, settings.MAX_CONCURRENT_REQUESTS_PER_ACCOUNT, priority)
    try:
        candidate = await _prepare_candidate(await client.send(client.build_request(method, url, headers=headers, content=content), stream=True))
    except Exception:
        lease.release()
        raise
    original_aclose = candidate.aclose

    async def close_with_lease():
        try:
            await original_aclose()
        finally:
            lease.release()

    candidate.aclose = close_with_lease
    return candidate


@router.post("/messages")
@router.post("/messages/count_tokens")
async def proxy_messages(
    request: Request,
    background_tasks: BackgroundTasks,
    key: ApiKeyDb = Depends(security.authenticate_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """Forward a Messages API call through a rotated subscription account, streaming the SSE response back."""
    request.state.proxy_event_request_id = request_context.get_request_context().get("request_id") or f"req_{uuid.uuid4().hex}"
    body = await request.body()
    is_count_tokens = request.url.path.rstrip("/").endswith("/count_tokens")
    request_reasoning = None
    requested_thinking_level = None
    requested_model = None
    request_model = None
    try:
        parsed_request = json.loads(body)
        if isinstance(parsed_request, dict):
            requested_model = parsed_request.get("model")
            request_model = requested_model
            request_reasoning = usage.reasoning_level_from_request(parsed_request)
            requested_thinking_level = thinking_level_from_request(parsed_request)
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass

    # We are mounted under /api but upstream expects the bare Anthropic path (/v1/messages); strip our mount prefix.
    upstream_path = request.url.path
    if upstream_path.startswith(config.API_PREFIX):
        upstream_path = upstream_path[len(config.API_PREFIX) :]
    upstream_url = f"{config.UPSTREAM_BASE_URL.rstrip('/')}{upstream_path}"
    if request.url.query:
        upstream_url = f"{upstream_url}?{request.url.query}"

    user_id = key.user_id
    api_key_id = key.id
    user = db.query(UserDb).filter(UserDb.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=401, detail="API key owner no longer exists")

    _set_archive_metadata(
        request,
        user_id=user_id,
        api_key_id=api_key_id,
        operation="messages.count_tokens" if is_count_tokens else "messages",
        requested_model=requested_model,
        upstream_model=request_model,
        reasoning_level=request_reasoning,
    )

    if user is not None and isinstance(parsed_request, dict) and request_model is not None:
        effective_model = _override_model(user, request_model)
        if effective_model != request_model:
            parsed_request["model"] = effective_model
            body = json.dumps(parsed_request, separators=(",", ":")).encode()
            request_model = effective_model
            _set_archive_metadata(request, upstream_model=request_model)

    if user is not None and requested_thinking_level is not None and requested_thinking_level not in user.allowed_thinking_levels:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Thinking level '{requested_thinking_level}' is not allowed for this user.",
        )
    request.state.proxy_event_context = {
        "model": request_model,
        "requested_model": requested_model,
        "thinking_level": requested_thinking_level or request_reasoning,
        "user_priority": user.priority,
    }
    _emit_event(request, "request.received", user_id=user_id, api_key_id=api_key_id, metadata={"path": request.url.path, "method": request.method})

    # Per-user limits (across ALL of this user's keys), enforced before opening any upstream connection. Unlike keys,
    # users have no global default -- a null/0 limit means no user-level cap.
    if user is not None and user.rate_limit_per_minute and user.rate_limit_per_minute > 0:
        window_start = datetime.now(timezone.utc) - timedelta(seconds=60)
        recent_user_requests = db.query(UsageRecordDb).filter(UsageRecordDb.user_id == user_id, UsageRecordDb.created_at >= window_start).count()
        if recent_user_requests >= user.rate_limit_per_minute:
            notifications.enqueue_client_limit(
                db,
                "user_rate_limit",
                user_name=user.name,
                limit=user.rate_limit_per_minute,
                dedupe_key=str(user.id),
                dashboard_url=settings.FRONTEND_ORIGIN,
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="User rate limit exceeded; slow down.",
                headers={"Retry-After": "60"},
            )
    if user is not None and user.monthly_token_budget and user.monthly_token_budget > 0:
        if usage.monthly_token_usage(db, user_id) >= user.monthly_token_budget:
            notifications.enqueue_client_limit(
                db,
                "user_monthly_budget",
                user_name=user.name,
                limit=user.monthly_token_budget,
                dedupe_key=f"{user.id}:{datetime.now(timezone.utc):%Y-%m}",
                dashboard_url=settings.FRONTEND_ORIGIN,
            )
            db.commit()
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User monthly token budget exhausted.")
    if user is not None and user.lifetime_token_budget and user.lifetime_token_budget > 0:
        if usage.total_token_usage(db, user_id) >= user.lifetime_token_budget:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User lifetime token budget exhausted.")
    if user is not None and user.monthly_spend_budget_usd and user.monthly_spend_budget_usd > 0:
        if usage.spend_usage(db, user_id=user_id, month_to_date=True) >= user.monthly_spend_budget_usd:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User monthly spend budget exhausted.")
    if user is not None and user.lifetime_spend_budget_usd and user.lifetime_spend_budget_usd > 0:
        if usage.spend_usage(db, user_id=user_id) >= user.lifetime_spend_budget_usd:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User lifetime spend budget exhausted.")

    # Per-key limits, enforced before opening any upstream connection.
    rate_limit = key.rate_limit_per_minute if key.rate_limit_per_minute is not None else settings.DEFAULT_KEY_RATE_LIMIT_PER_MINUTE
    if rate_limit and rate_limit > 0:
        window_start = datetime.now(timezone.utc) - timedelta(seconds=60)
        recent_requests = db.query(UsageRecordDb).filter(UsageRecordDb.api_key_id == api_key_id, UsageRecordDb.created_at >= window_start).count()
        if recent_requests >= rate_limit:
            notifications.enqueue_client_limit(
                db,
                "api_key_rate_limit",
                user_name=user.name if user is not None else "Unknown user",
                key_label=key.label,
                key_prefix=key.key_prefix,
                limit=rate_limit,
                dedupe_key=str(key.id),
                dashboard_url=settings.FRONTEND_ORIGIN,
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="API key rate limit exceeded; slow down.",
                headers={"Retry-After": "60"},
            )
    if key.monthly_token_budget and key.monthly_token_budget > 0:
        if usage.monthly_token_usage_for_key(db, api_key_id) >= key.monthly_token_budget:
            notifications.enqueue_client_limit(
                db,
                "api_key_monthly_budget",
                user_name=user.name if user is not None else "Unknown user",
                key_label=key.label,
                key_prefix=key.key_prefix,
                limit=key.monthly_token_budget,
                dedupe_key=f"{key.id}:{datetime.now(timezone.utc):%Y-%m}",
                dashboard_url=settings.FRONTEND_ORIGIN,
            )
            db.commit()
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API key monthly token budget exhausted.")

    client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=15.0))

    exclude_ids = set()
    resp = None
    chosen_id = None
    chosen_fallback_id = None

    # Priority routing always walks the whole pool before declaring exhaustion.
    max_attempts = db.query(AccountDb).count()

    # Account selection with transparent failover on rate limits.
    for _ in range(max_attempts):
        account = rotation.select_account(db, user, exclude_ids)
        if account is None:
            break
        _emit_event(
            request, "account.attempt", user_id=user_id, api_key_id=api_key_id, account_id=account.id, metadata={"priority": account.priority}
        )

        try:
            access_token = rotation.ensure_fresh_token(db, account)
            headers = _build_upstream_headers(request.headers, access_token)
            db.commit()
            candidate = await _send_with_account_limit(client, request.method, upstream_url, headers, body, account, user.priority)
            if candidate.status_code == 401:
                await candidate.aclose()
                access_token = rotation.ensure_fresh_token(db, account, force_refresh=True)
                candidate = await _send_with_account_limit(
                    client,
                    request.method,
                    upstream_url,
                    _build_upstream_headers(request.headers, access_token),
                    body,
                    account,
                    user.priority,
                )
                if candidate.status_code == 401:
                    await candidate.aclose()
                    provider_health.persist_failure(db, account.id, provider_health.reauthentication_error())
                    exclude_ids.add(account.id)
                    continue
        except account_limiter.AccountBusy:
            logger.info("Pooled account %s is at its in-flight request ceiling; trying the next account", account.label)
            exclude_ids.add(account.id)
            _emit_event(
                request,
                "account.busy",
                user_id=user_id,
                api_key_id=api_key_id,
                account_id=account.id,
                message="Per-account concurrency ceiling reached",
            )
            continue
        except Exception as exc:  # noqa: BLE001
            provider_health.persist_failure(db, account.id, exc)
            exclude_ids.add(account.id)
            _emit_event(request, "account.error", user_id=user_id, api_key_id=api_key_id, account_id=account.id, message=str(exc))
            continue

        if await _is_capacity_unavailable(candidate):
            _emit_event(
                request,
                "account.capacity",
                user_id=user_id,
                api_key_id=api_key_id,
                account_id=account.id,
                status_code=candidate.status_code,
                message="Provider reported model capacity",
            )
            await candidate.aclose()
            rotation.mark_cooldown(db, account, account.cooldown_seconds)
            _emit_event(
                request,
                "account.cooldown",
                user_id=user_id,
                api_key_id=api_key_id,
                account_id=account.id,
                message=f"Cooling down for {account.cooldown_seconds}s",
            )
            logger.warning(
                "Pooled account %s received explicit model-capacity response; cooling down and failing over",
                account.label,
            )
            db.commit()
            exclude_ids.add(account.id)
            continue

        unified_status = rotation.update_quota_from_headers(account, candidate.headers)
        provider_health.mark_response(account, candidate)
        if unified_status in rotation.HARD_LIMIT_STATUSES:
            notifications.enqueue_account_hard_limit(db, account, settings.FRONTEND_ORIGIN)
        else:
            notifications.enqueue_account_threshold(db, account, settings.FRONTEND_ORIGIN)
        db.commit()

        if candidate.status_code == 429 or unified_status in rotation.HARD_LIMIT_STATUSES:
            retry_after = rotation.parse_retry_after(candidate.headers, account.cooldown_seconds)
            await candidate.aclose()
            rotation.mark_cooldown(db, account, retry_after)
            _emit_event(
                request,
                "account.rate_limited",
                user_id=user_id,
                api_key_id=api_key_id,
                account_id=account.id,
                status_code=429,
                message=f"Cooling down for {retry_after}s",
            )
            exclude_ids.add(account.id)
            continue

        if candidate.status_code < 400:
            background_tasks.add_task(warmup.warm_pool_if_needed)
        resp = candidate
        chosen_id = account.id
        _emit_event(request, "account.selected", user_id=user_id, api_key_id=api_key_id, account_id=account.id, status_code=candidate.status_code)
        break

    # Pay-as-you-go credentials are a true fallback tier: they are considered
    # only after every eligible subscription account has failed or exhausted.
    if resp is None:
        fallback_excluded: set[uuid.UUID] = set()
        max_fallback_attempts = db.query(AnthropicFallbackDb).count() if user.fallback_enabled else 0
        for _ in range(max_fallback_attempts):
            fallback = anthropic_fallbacks.select_provider(
                db,
                fallback_excluded,
                model=request_model if isinstance(request_model, str) else None,
            )
            if fallback is None:
                break
            _emit_event(request, "fallback.attempt", user_id=user_id, api_key_id=api_key_id, fallback_provider_id=fallback.id)
            fallback_url = anthropic_fallbacks.endpoint(fallback, upstream_path)
            if request.url.query:
                fallback_url = f"{fallback_url}?{request.url.query}"
            try:
                candidate = await _send_with_account_limit(
                    client,
                    request.method,
                    fallback_url,
                    _build_fallback_headers(request.headers, anthropic_fallbacks.api_key(fallback)),
                    body,
                    fallback,
                    user.priority,
                )
            except account_limiter.AccountBusy:
                logger.info("Fallback provider %s is at its in-flight request ceiling; trying the next provider", fallback.label)
                fallback_excluded.add(fallback.id)
                _emit_event(
                    request,
                    "fallback.busy",
                    user_id=user_id,
                    api_key_id=api_key_id,
                    fallback_provider_id=fallback.id,
                    message="Per-provider concurrency ceiling reached",
                )
                continue
            except Exception as exc:  # noqa: BLE001
                anthropic_fallbacks.mark_cooldown(fallback, 60, f"Request failed: {exc}")
                db.commit()
                fallback_excluded.add(fallback.id)
                _emit_event(request, "fallback.error", user_id=user_id, api_key_id=api_key_id, fallback_provider_id=fallback.id, message=str(exc))
                continue

            if await _is_capacity_unavailable(candidate):
                _emit_event(
                    request,
                    "fallback.capacity",
                    user_id=user_id,
                    api_key_id=api_key_id,
                    fallback_provider_id=fallback.id,
                    status_code=candidate.status_code,
                    message="Provider reported model capacity",
                )
                await candidate.aclose()
                anthropic_fallbacks.mark_cooldown(fallback, 60, "Upstream reported model capacity.")
                logger.warning(
                    "Fallback provider %s received explicit model-capacity response; cooling down and failing over",
                    fallback.label,
                )
                db.commit()
                fallback_excluded.add(fallback.id)
                continue

            if candidate.status_code == 401:
                await candidate.aclose()
                anthropic_fallbacks.mark_invalid(fallback, "Credential rejected with HTTP 401.")
                db.commit()
                fallback_excluded.add(fallback.id)
                continue
            if candidate.status_code == 429 or candidate.status_code >= 500:
                retry_after = rotation.parse_retry_after(candidate.headers, 60)
                await candidate.aclose()
                anthropic_fallbacks.mark_cooldown(
                    fallback,
                    retry_after,
                    f"Upstream returned HTTP {candidate.status_code}.",
                )
                db.commit()
                fallback_excluded.add(fallback.id)
                continue
            if candidate.status_code in {403, 404}:
                await candidate.aclose()
                anthropic_fallbacks.mark_cooldown(
                    fallback,
                    60,
                    f"Upstream returned HTTP {candidate.status_code}.",
                )
                db.commit()
                fallback_excluded.add(fallback.id)
                continue

            if candidate.status_code < 400:
                anthropic_fallbacks.mark_healthy(fallback)
                db.commit()
            resp = candidate
            chosen_fallback_id = fallback.id
            _emit_event(
                request,
                "fallback.selected",
                user_id=user_id,
                api_key_id=api_key_id,
                fallback_provider_id=fallback.id,
                status_code=candidate.status_code,
            )
            break

    if resp is None or (chosen_id is None and chosen_fallback_id is None):
        _emit_event(
            request,
            "request.exhausted",
            user_id=user_id,
            api_key_id=api_key_id,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message="No subscription account or API fallback could serve the request",
        )
        await client.aclose()
        notifications.enqueue_pool_unavailable(db, settings.FRONTEND_ORIGIN)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="All subscription accounts and API fallbacks are exhausted, disabled, over budget, or unavailable. Try again shortly.",
        )

    response_headers = _pool_quota_response_headers(
        db,
        {key: value for key, value in resp.headers.items() if key.lower() not in _STRIP_RESPONSE_HEADERS},
    )
    upstream_request_id = resp.headers.get("request-id") or resp.headers.get("x-request-id")
    content_type = resp.headers.get("content-type", "")
    _emit_event(
        request,
        "response.returned",
        user_id=user_id,
        api_key_id=api_key_id,
        account_id=chosen_id,
        fallback_provider_id=chosen_fallback_id,
        status_code=resp.status_code,
    )
    _set_archive_metadata(
        request,
        account_id=chosen_id,
        fallback_provider_id=chosen_fallback_id,
        upstream_request_id=upstream_request_id,
    )
    # Keep usage and events on the same proxy-generated correlation ID; the
    # upstream provider ID is preserved separately in the request archive.
    request_id = request.state.proxy_event_request_id

    # Non-streaming JSON (count_tokens, stream:false).
    if resp.status_code >= 400 or "text/event-stream" not in content_type:
        raw = await resp.aread()
        await resp.aclose()
        await client.aclose()
        raw = _restore_requested_model_in_error(raw, resp.status_code, requested_model, request_model)

        if not is_count_tokens:
            parsed_usage = usage.Usage(reasoning_level=request_reasoning)
            try:
                parsed_usage = usage.usage_from_json(
                    json.loads(raw),
                    reasoning_level=request_reasoning,
                )
            except (json.JSONDecodeError, ValueError):
                pass
            _archive_usage(request, parsed_usage)
            _record_usage_safe(
                user_id,
                api_key_id,
                chosen_id,
                parsed_usage,
                resp.status_code,
                request_id,
                chosen_fallback_id,
            )

        return Response(
            content=raw,
            status_code=resp.status_code,
            headers=response_headers,
            media_type=content_type or "application/json",
            background=background_tasks,
        )

    # Streaming SSE: pass through while capturing usage.
    accumulator = usage.StreamUsageAccumulator(reasoning_level=request_reasoning)
    status_code = resp.status_code

    async def stream_body():
        try:
            async for chunk in resp.aiter_bytes():
                accumulator.feed(chunk)
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()
            captured_usage = accumulator.result()
            _archive_usage(request, captured_usage)
            _record_usage_safe(
                user_id,
                api_key_id,
                chosen_id,
                captured_usage,
                status_code,
                request_id,
                chosen_fallback_id,
            )

    return StreamingResponse(
        stream_body(),
        status_code=status_code,
        headers=response_headers,
        media_type="text/event-stream",
        background=background_tasks,
    )
