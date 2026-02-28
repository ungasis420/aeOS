"""
tests/test_ai_infer.py

Pytest unit tests for `src.ai.ai_infer`.

All HTTP calls are mocked so tests run without Ollama.
Stamp: S✅ T✅ L✅ A✅
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest
import requests

# Ensure repo root is importable when running `pytest` from different CWDs.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.ai import ai_infer


def _mk_chat_resp(
    content: str = "hello",
    *,
    model: str = "fake-model",
    prompt_eval_count: int = 1,
    eval_count: int = 2,
    status_code: int = 200,
):
    """Create a mock `requests.Response` for the /api/chat endpoint."""
    resp = MagicMock()
    resp.status_code = int(status_code)
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "message": {"content": content},
        "model": model,
        "prompt_eval_count": int(prompt_eval_count),
        "eval_count": int(eval_count),
    }
    return resp


@pytest.fixture(autouse=True)
def _reset_stats():
    """Reset module-local stats to avoid cross-test leakage."""
    ai_infer._STATS = ai_infer._InferenceStats()  # type: ignore[attr-defined]


def test_infer_returns_dict_with_required_keys():
    """infer() should return the stable contract keys on success."""
    with patch("src.ai.ai_infer.requests.post", return_value=_mk_chat_resp(content="ok")):
        out = ai_infer.infer("hi")

    assert isinstance(out, dict)
    for k in ("response", "model", "tokens_used", "latency_ms", "success"):
        assert k in out

    assert out["success"] is True
    assert out["response"] == "ok"
    assert out["model"] == "fake-model"
    assert out["tokens_used"] == 3
    assert isinstance(out["latency_ms"], int)


def test_infer_json_parses_valid_json():
    """infer_json() should parse valid JSON strings returned by the model."""
    payload = '{"a": 1, "b": "two"}'

    with patch("src.ai.ai_infer.requests.post", return_value=_mk_chat_resp(content=payload)):
        out = ai_infer.infer_json(prompt="Return JSON", schema_hint='{"a": 1}')

    assert isinstance(out, dict)
    assert out.get("success") is True
    assert out.get("data") == {"a": 1, "b": "two"}
    assert out.get("raw") == payload


def test_retry_logic_on_timeout():
    """infer() should retry on requests.Timeout up to 3 attempts."""
    side_effect = [
        requests.exceptions.Timeout("t1"),
        requests.exceptions.Timeout("t2"),
        _mk_chat_resp(content="finally"),
    ]

    # Patch sleep to keep tests fast + deterministic.
    with patch("src.ai.ai_infer.time.sleep", return_value=None) as _sleep:
        with patch("src.ai.ai_infer.requests.post", side_effect=side_effect) as post:
            out = ai_infer.infer("hi")

    assert out.get("success") is True
    assert out.get("response") == "finally"
    assert post.call_count == 3
    assert _sleep.call_count == 2


def test_get_inference_stats_returns_dict():
    """get_inference_stats() should accumulate across multiple infer() calls."""
    with patch(
        "src.ai.ai_infer.requests.post",
        return_value=_mk_chat_resp(content="x", prompt_eval_count=2, eval_count=3),
    ):
        ai_infer.infer("one")
        ai_infer.infer("two")

    stats = ai_infer.get_inference_stats()
    assert isinstance(stats, dict)

    # Snapshot contract.
    for k in ("total_calls", "avg_latency_ms", "total_tokens", "success_rate"):
        assert k in stats

    assert stats["total_calls"] == 2
    assert stats["total_tokens"] == 10
    assert stats["success_rate"] == 1.0
    assert isinstance(stats["avg_latency_ms"], float)
