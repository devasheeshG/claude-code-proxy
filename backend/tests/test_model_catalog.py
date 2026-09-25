import pytest

from app import pricing
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


def test_latest_opus_is_in_default_catalog():
    assert "claude-opus-5-5" in DEFAULT_MODEL_IDS


@pytest.mark.parametrize(
    ("model", "rates"),
    [
        ("claude-fable-5-1", (10.0, 50.0, 12.5, 20.0, 0.25)),
        ("claude-opus-5", (5.0, 25.0, 6.25, 10.0, 0.5)),
        ("claude-opus-5-5", (4.0, 20.0, 5.0, 8.0, 0.2)),
        ("claude-sonnet-5", (2.0, 10.0, 2.5, 4.0, 0.2)),
    ],
)
def test_current_model_api_equivalent_pricing(model, rates):
    input_rate, output_rate, write_5m_rate, write_1h_rate, read_rate = rates
    actual = pricing.cost_usd(
        model,
        input_tokens=10,
        output_tokens=20,
        cache_creation_5m_input_tokens=30,
        cache_creation_1h_input_tokens=40,
        cache_read_input_tokens=50,
    )
    expected = (10 * input_rate + 20 * output_rate + 30 * write_5m_rate + 40 * write_1h_rate + 50 * read_rate) / 1_000_000
    assert actual == pytest.approx(expected)
