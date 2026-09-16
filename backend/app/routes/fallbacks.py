# Path: app/routes/fallbacks.py
# Description: Admin CRUD, lifecycle, and health checks for Anthropic-compatible fallback credentials.

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.utils import anthropic_fallbacks, crypto, egress, security
from app.utils.models.api import (
    AccountStatus,
    AnthropicFallbackResponse,
    CreateAnthropicFallbackRequest,
    ListAnthropicFallbacksResponse,
    ProviderHealth,
    UpdateAnthropicFallbackRequest,
)
from app.utils.postgres import AnthropicFallbackDb, UsageRecordDb, get_db

router = APIRouter(tags=["Anthropic fallbacks"], prefix="/fallbacks")


def _provider_or_404(db: Session, provider_id: uuid.UUID) -> AnthropicFallbackDb:
    provider = db.get(AnthropicFallbackDb, provider_id)
    if provider is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fallback provider not found")
    return provider


def _clean_label(value: str) -> str:
    label = value.strip()
    if not label:
        raise HTTPException(status_code=422, detail="Label cannot be blank")
    return label


@router.get("", response_model=ListAnthropicFallbacksResponse)
def list_fallbacks(
    _: str = Depends(security.require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> ListAnthropicFallbacksResponse:
    anthropic_fallbacks.normalize_expired_cooldowns(db)
    providers = db.query(AnthropicFallbackDb).order_by(AnthropicFallbackDb.priority.asc(), AnthropicFallbackDb.created_at.asc()).all()
    return ListAnthropicFallbacksResponse(fallbacks=[anthropic_fallbacks.to_api(db, provider) for provider in providers])


@router.post("", response_model=AnthropicFallbackResponse, status_code=status.HTTP_201_CREATED)
def create_fallback(
    request: CreateAnthropicFallbackRequest,
    _: str = Depends(security.require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> AnthropicFallbackResponse:
    now = datetime.now(timezone.utc)
    base_url = anthropic_fallbacks.normalize_base_url(request.base_url)
    raw_key = request.api_key.strip()
    target_id = request.egress_target_id or egress.get_pool().default_target().id
    if not egress.get_pool().has_target(target_id):
        raise HTTPException(status_code=422, detail=f"Egress target '{target_id}' is not configured or enabled")
    provider = AnthropicFallbackDb(
        id=uuid.uuid4(),
        label=_clean_label(request.label),
        base_url=base_url,
        api_key_enc=crypto.encrypt(raw_key),
        credential_hash=anthropic_fallbacks.credential_hash(base_url, raw_key),
        key_hint=anthropic_fallbacks.key_hint(raw_key),
        status=AccountStatus.ACTIVE,
        provider_health=ProviderHealth.UNKNOWN,
        priority=request.priority,
        egress_target_id=target_id,
        monthly_spend_limit_usd=request.monthly_spend_limit_usd,
        created_at=now,
        updated_at=now,
    )
    db.add(provider)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This API key is already connected to that base URL.") from exc
    db.refresh(provider)
    return AnthropicFallbackResponse(fallback=anthropic_fallbacks.to_api(db, provider))


@router.put("/{provider_id}", response_model=AnthropicFallbackResponse)
def update_fallback(
    provider_id: uuid.UUID,
    request: UpdateAnthropicFallbackRequest,
    _: str = Depends(security.require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> AnthropicFallbackResponse:
    provider = _provider_or_404(db, provider_id)
    changed_credentials = request.api_key is not None or request.base_url is not None
    base_url = anthropic_fallbacks.normalize_base_url(request.base_url or provider.base_url)
    raw_key = request.api_key.strip() if request.api_key is not None else anthropic_fallbacks.api_key(provider)
    if request.label is not None:
        provider.label = _clean_label(request.label)
    provider.base_url = base_url
    if request.api_key is not None:
        provider.api_key_enc = crypto.encrypt(raw_key)
        provider.key_hint = anthropic_fallbacks.key_hint(raw_key)
    provider.credential_hash = anthropic_fallbacks.credential_hash(base_url, raw_key)
    if request.clear_monthly_spend_limit:
        provider.monthly_spend_limit_usd = None
    elif request.monthly_spend_limit_usd is not None:
        provider.monthly_spend_limit_usd = request.monthly_spend_limit_usd
    if request.priority is not None:
        provider.priority = request.priority
    pool = egress.get_pool()
    if "egress_target_id" in request.model_fields_set:
        target_id = request.egress_target_id or pool.default_target().id
        if not pool.has_target(target_id):
            raise HTTPException(status_code=422, detail=f"Egress target '{target_id}' is not configured or enabled")
        provider.egress_target_id = target_id
    elif provider.egress_target_id is None:
        provider.egress_target_id = pool.default_target().id
    if changed_credentials:
        provider.provider_health = ProviderHealth.UNKNOWN
        provider.provider_health_message = None
        provider.provider_health_checked_at = None
        provider.model_catalog_json = None
        provider.model_catalog_refreshed_at = None
        provider.cooldown_until = None
        if provider.status == AccountStatus.COOLDOWN:
            provider.status = AccountStatus.ACTIVE
    provider.updated_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This API key is already connected to that base URL.") from exc
    return AnthropicFallbackResponse(fallback=anthropic_fallbacks.to_api(db, provider))


@router.post("/{provider_id}/enable", response_model=AnthropicFallbackResponse)
def enable_fallback(
    provider_id: uuid.UUID,
    _: str = Depends(security.require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> AnthropicFallbackResponse:
    provider = _provider_or_404(db, provider_id)
    provider.status = AccountStatus.ACTIVE
    provider.cooldown_until = None
    provider.updated_at = datetime.now(timezone.utc)
    db.commit()
    return AnthropicFallbackResponse(fallback=anthropic_fallbacks.to_api(db, provider))


@router.post("/{provider_id}/disable", response_model=AnthropicFallbackResponse)
def disable_fallback(
    provider_id: uuid.UUID,
    _: str = Depends(security.require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> AnthropicFallbackResponse:
    provider = _provider_or_404(db, provider_id)
    provider.status = AccountStatus.DISABLED
    provider.cooldown_until = None
    provider.updated_at = datetime.now(timezone.utc)
    db.commit()
    return AnthropicFallbackResponse(fallback=anthropic_fallbacks.to_api(db, provider))


@router.post("/{provider_id}/test", response_model=AnthropicFallbackResponse)
def test_fallback(
    provider_id: uuid.UUID,
    _: str = Depends(security.require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> AnthropicFallbackResponse:
    provider = _provider_or_404(db, provider_id)
    try:
        target = egress.get_pool().resolve(provider.egress_target_id)
        with egress.sync_client(target, 30.0) as client:
            response = client.get(
                anthropic_fallbacks.endpoint(provider, "/v1/models"),
                headers={
                    "x-api-key": anthropic_fallbacks.api_key(provider),
                    "anthropic-version": "2023-06-01",
                },
            )
        if response.status_code in {401, 403}:
            anthropic_fallbacks.mark_invalid(provider, f"Credential rejected with HTTP {response.status_code}.")
        elif response.is_success:
            payload = response.json()
            models = payload.get("data") if isinstance(payload, dict) else None
            if isinstance(models, list):
                provider.model_catalog_json = json.dumps(models, separators=(",", ":"))
                provider.model_catalog_refreshed_at = datetime.now(timezone.utc)
            anthropic_fallbacks.mark_healthy(provider)
        else:
            anthropic_fallbacks.mark_cooldown(provider, 60, f"Health check returned HTTP {response.status_code}.")
    except Exception as exc:  # noqa: BLE001
        anthropic_fallbacks.mark_cooldown(provider, 60, f"Health check failed: {exc}")
    db.commit()
    return AnthropicFallbackResponse(fallback=anthropic_fallbacks.to_api(db, provider))


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_fallback(
    provider_id: uuid.UUID,
    _: str = Depends(security.require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> None:
    provider = _provider_or_404(db, provider_id)
    db.query(UsageRecordDb).filter(UsageRecordDb.fallback_provider_id == provider.id).update(
        {UsageRecordDb.fallback_provider_id: None},
        synchronize_session=False,
    )
    db.delete(provider)
    db.commit()
