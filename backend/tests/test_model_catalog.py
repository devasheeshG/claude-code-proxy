from app.config import get_settings
from app.model_catalog import DEFAULT_MODEL_IDS, configured_model_ids


def test_model_allowlist_reads_comma_separated_environment(monkeypatch):
    monkeypatch.setenv("ALLOWED_MODELS", " claude-custom, claude-custom, claude-next ")
    get_settings.cache_clear()
    try:
        assert configured_model_ids() == ("claude-custom", "claude-next")
    finally:
        get_settings.cache_clear()


def test_blank_model_allowlist_keeps_safe_defaults():
    assert configured_model_ids("") == DEFAULT_MODEL_IDS
