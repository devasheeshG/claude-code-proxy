"""Shared thinking-effort values and request parsing helpers."""

from typing import Mapping, Optional, Tuple

THINKING_LEVELS: Tuple[str, ...] = ("low", "medium", "high", "max")


def thinking_level_from_request(body: Mapping) -> Optional[str]:
    """Return the explicit effort level requested by a Messages API call, if any."""
    output_config = body.get("output_config")
    thinking = body.get("thinking")
    candidates = []
    if isinstance(output_config, Mapping):
        candidates.append(output_config.get("effort"))
    if isinstance(thinking, Mapping):
        candidates.append(thinking.get("effort"))
    candidates.append(body.get("effort"))

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip().lower()
    return None
