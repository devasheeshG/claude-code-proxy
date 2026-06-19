"""Canonical parsing and persistence helpers for per-user model policies."""

from __future__ import annotations

import json
from typing import Dict, Optional


def normalize_model_overrides(values: object) -> Dict[str, str]:
    """Normalize requested-model -> upstream-model mappings for exact matching."""
    if not isinstance(values, dict):
        return {}
    normalized: Dict[str, str] = {}
    for raw_source, raw_target in values.items():
        if not isinstance(raw_source, str) or not isinstance(raw_target, str):
            continue
        source = raw_source.strip().lower()
        target = raw_target.strip().lower()
        if source and target:
            normalized[source] = target
    return normalized


def encode_model_overrides(values: object) -> str:
    return json.dumps(normalize_model_overrides(values), separators=(",", ":"), sort_keys=True)


def decode_model_overrides(raw: Optional[str]) -> Dict[str, str]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return normalize_model_overrides(parsed)
