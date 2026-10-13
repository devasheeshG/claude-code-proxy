"""Flush final SSE data and distinguish unknown metrics from reported zero."""

from app.utils import usage


def test_final_usage_without_newline_is_preserved():
    accumulator = usage.StreamUsageAccumulator()
    accumulator.feed(b'data: {"type":"message_start","message":{"model":"claude-sonnet-4-6","usage":{"input_tokens":15}}}\n\n')
    accumulator.feed(b'data: {"type":"message_delta","usage":{"output_tokens":20}}')
    result = accumulator.result()
    assert result.input_tokens == 15
    assert result.output_tokens == 20
    assert result.usage_reported is True


def test_reported_zero_is_distinct_from_absent_usage():
    assert usage.usage_from_json({"usage": {"input_tokens": 0, "output_tokens": 0}}).usage_reported
    assert not usage.usage_from_json({"type": "error"}).usage_reported
