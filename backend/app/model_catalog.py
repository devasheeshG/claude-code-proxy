"""Fixed Claude model choices exposed by the proxy dashboard.

Keep model discovery deterministic and independent of observed traffic or
fallback-provider availability. Update this tuple deliberately as supported
Sonnet, Haiku, Opus, and Fable releases change.
"""

MODEL_IDS: tuple[str, ...] = (
    "claude-fable-5",
    "claude-fable-5-1",
    "claude-haiku-4-5-20251001",
    "claude-opus-4-6",
    "claude-opus-4-8",
    "claude-opus-5",
    "claude-sonnet-5",
)
