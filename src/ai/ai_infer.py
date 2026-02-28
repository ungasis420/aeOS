"""
aeOS Phase 4 — Layer 1 (AI Core)

ai_infer.py — Core inference wrapper for Ollama (LOCAL_LLM_BRIDGE primitive).

This module provides a small, reliable interface for:
- single-shot inference
- inference with prepended context
- JSON-structured inference with parsing
- token streaming

Stamp: S✅ T✅ L✅ A✅
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, Generator, Optional, Tuple

import requests

from src.core.config import AI_MAX_TOKENS, AI_TEMPERATURE, AI_TIMEOUT, OLLAMA_HOST, OLLAMA_MODEL
from src.core.logger import get_logger

_LOG = get_logger(__name__)


# ---------------------------------------------------------------------------
# Internal stats (process-local)
# ---------------------------------------------------------------------------


class _InferenceStats:
    """Thread-safe in-process inference statistics accumulator."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total_calls = 0
        self._total_success = 0
        self._total_latency_ms = 0
        self._total_tokens = 0

    def record(self, latency_ms: int, tokens_used: int, success: bool) -> None:
        """Record a single inference call result."""
        latency_ms_i = max(0, int(latency_ms))
        tokens_i = max(0, int(tokens_used))
        with self._lock:
            self._total_calls += 1
            self._total_latency_ms += latency_ms_i
            self._total_tokens += tokens_i
            if success:
                self._total_success += 1

    def snapshot(self) -> Dict[str, Any]:
        """Return a point-in-time snapshot of stats."""
        with self._lock:
            total_calls = self._total_calls
            total_success = self._total_success
            total_latency_ms = self._total_latency_ms
            total_tokens = self._total_tokens
        avg_latency_ms = (total_latency_ms / total_calls) if total_calls else 0.0
        success_rate = (total_success / total_calls) if total_calls else 0.0
        return {
            "total_calls": total_calls,
            "avg_latency_ms": avg_latency_ms,
            "total_tokens": total_tokens,
            "success_rate": success_rate,
        }


_STATS = _InferenceStats()


def get_inference_stats() -> Dict[str, Any]:
    """
    Return aggregate inference statistics for the current process.

    Returns:
        dict: {total_calls, avg_latency_ms, total_tokens, success_rate}
    """
    return _STATS.snapshot()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class _EndpointNotFound(RuntimeError):
    """Raised when an Ollama endpoint is not available (e.g., older server)."""


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _host_base() -> str:
    return (OLLAMA_HOST or "").rstrip("/") or "http://localhost:11434"


def _ollama_url(path: str) -> str:
    path_clean = path if path.startswith("/") else f"/{path}"
    return f"{_host_base()}{path_clean}"


def _ollama_options() -> Dict[str, Any]:
    """
    Ollama 'options' payload.
    Note: keep minimal and stable; model-specific knobs can be added later.
    """
    return {
        "temperature": AI_TEMPERATURE,
        # "num_predict" is Ollama's max generation token cap (approx).
        "num_predict": AI_MAX_TOKENS,
    }


def _extract_tokens_used(payload: Dict[str, Any]) -> int:
    # Ollama commonly returns these fields on final response objects.
    return _safe_int(payload.get("prompt_eval_count")) + _safe_int(payload.get("eval_count"))


def _find_first_json_span(text: str) -> Optional[Tuple[int, int]]:
    """
    Return (start, end_exclusive) of the first complete JSON object/array in text.
    Handles nested objects/arrays and ignores braces inside JSON strings.
    """
    start: Optional[int] = None
    stack: list[str] = []
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_string = False
            continue
        # Not in string
        if ch == '"':
            in_string = True
            continue
        if ch == "{" or ch == "[":
            if start is None:
                start = i
            stack.append("}" if ch == "{" else "]")
            continue
        if ch == "}" or ch == "]":
            if stack and ch == stack[-1]:
                stack.pop()
                if start is not None and not stack:
                    return (start, i + 1)
    return None


def _parse_json_from_text(text: str) -> Tuple[Optional[Any], bool]:
    """
    Attempt to parse JSON from arbitrary model output.

    Returns:
        (data, ok)
    """
    stripped = (text or "").strip()
    if not stripped:
        return None, False
    # Best case: model returned raw JSON only.
    try:
        return json.loads(stripped), True
    except json.JSONDecodeError:
        pass
    # Common case: model wrapped JSON with explanation; extract first JSON span.
    span = _find_first_json_span(stripped)
    if not span:
        return None, False
    candidate = stripped[span[0] : span[1]]
    try:
        return json.loads(candidate), True
    except json.JSONDecodeError:
        return None, False


def _post_json(url: str, payload: Dict[str, Any], timeout_s: float, stream: bool = False) -> requests.Response:
    """
    POST JSON to Ollama with consistent headers.
    """
    headers = {"Content-Type": "application/json"}
    return requests.post(url, headers=headers, json=payload, timeout=timeout_s, stream=stream)


def _call_ollama_once(prompt: str, system_prompt: Optional[str], timeout_s: float) -> Tuple[str, str, int]:
    """
    Call Ollama once (no retries here).
    Tries /api/chat first, falls back to /api/generate if /api/chat is not found.

    Returns:
        (response_text, model_used, tokens_used)
    """
    model = OLLAMA_MODEL
    options = _ollama_options()

    # Prefer /api/chat to support system prompts via messages.
    chat_payload: Dict[str, Any] = {
        "model": model,
        "messages": [],
        "stream": False,
        "options": options,
    }
    if system_prompt:
        chat_payload["messages"].append({"role": "system", "content": system_prompt})
    chat_payload["messages"].append({"role": "user", "content": prompt})

    chat_url = _ollama_url("/api/chat")
    try:
        resp = _post_json(chat_url, chat_payload, timeout_s=timeout_s, stream=False)
        if resp.status_code == 404:
            raise _EndpointNotFound("/api/chat not available")
        resp.raise_for_status()
        data = resp.json()
        text = ((data.get("message") or {}) or {}).get("content", "") or ""
        model_used = data.get("model") or model
        tokens_used = _extract_tokens_used(data)
        return text, model_used, tokens_used
    except _EndpointNotFound:
        # Fall back below.
        pass
    except ValueError as e:
        # JSON parse error from server response; treat as hard failure.
        raise RuntimeError(f"Ollama returned non-JSON response for /api/chat: {e}") from e

    # Fallback: /api/generate (works on older Ollama versions).
    gen_payload: Dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": options,
    }
    if system_prompt:
        gen_payload["system"] = system_prompt

    gen_url = _ollama_url("/api/generate")
    resp = _post_json(gen_url, gen_payload, timeout_s=timeout_s, stream=False)
    resp.raise_for_status()
    data = resp.json()
    text = (data.get("response") or "") or ""
    model_used = data.get("model") or model
    tokens_used = _extract_tokens_used(data)
    return text, model_used, tokens_used


def _infer_call(prompt: str, system_prompt: Optional[str]) -> Tuple[str, str, int, int, bool]:
    """
    Internal inference call with timeout retry logic.

    Returns:
        (response_text, model_used, tokens_used, latency_ms, success)
    """
    start = time.perf_counter()
    last_err: Optional[BaseException] = None

    for attempt in range(1, 4):  # 3 attempts on timeout
        try:
            text, model_used, tokens_used = _call_ollama_once(
                prompt=prompt,
                system_prompt=system_prompt,
                timeout_s=float(AI_TIMEOUT),
            )
            latency_ms = int((time.perf_counter() - start) * 1000)
            return text, model_used, tokens_used, latency_ms, True
        except requests.exceptions.Timeout as e:
            last_err = e
            _LOG.warning("Ollama timeout (attempt %s/3).", attempt)
            if attempt < 3:
                time.sleep(0.25 * attempt)
                continue
        except requests.exceptions.ConnectionError as e:
            last_err = e
            _LOG.error("Ollama connection error: %s", e)
            break
        except requests.exceptions.RequestException as e:
            last_err = e
            _LOG.error("Ollama request error: %s", e)
            break
        except Exception as e:  # noqa: BLE001 - surface unexpected failures cleanly
            last_err = e
            _LOG.exception("Unexpected inference failure.")
            break

    latency_ms = int((time.perf_counter() - start) * 1000)
    if last_err is not None:
        _LOG.debug("Inference failure detail: %r", last_err)
    return "", OLLAMA_MODEL, 0, latency_ms, False


def _stream_chat(
    prompt: str, system_prompt: Optional[str], timeout_s: float
) -> Generator[Tuple[str, Optional[Dict[str, Any]]], None, None]:
    """
    Stream from /api/chat.

    Yields:
        (chunk, final_payload_or_none)
    The final yield will have chunk="" and final_payload set.
    """
    model = OLLAMA_MODEL
    options = _ollama_options()
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [],
        "stream": True,
        "options": options,
    }
    if system_prompt:
        payload["messages"].append({"role": "system", "content": system_prompt})
    payload["messages"].append({"role": "user", "content": prompt})

    url = _ollama_url("/api/chat")
    resp = _post_json(url, payload, timeout_s=timeout_s, stream=True)
    if resp.status_code == 404:
        resp.close()
        raise _EndpointNotFound("/api/chat not available")
    resp.raise_for_status()

    final_payload: Optional[Dict[str, Any]] = None
    try:
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                # Skip malformed line; keep streaming.
                continue
            if obj.get("error"):
                raise RuntimeError(str(obj.get("error")))
            msg = (obj.get("message") or {}) if isinstance(obj.get("message"), dict) else {}
            chunk = (msg.get("content") or "") if isinstance(msg.get("content"), str) else ""
            if chunk:
                yield chunk, None
            if bool(obj.get("done")):
                final_payload = obj
                break
    finally:
        resp.close()
    yield "", final_payload


def _stream_generate(
    prompt: str, system_prompt: Optional[str], timeout_s: float
) -> Generator[Tuple[str, Optional[Dict[str, Any]]], None, None]:
    """
    Stream from /api/generate.

    Yields:
        (chunk, final_payload_or_none)
    The final yield will have chunk="" and final_payload set.
    """
    model = OLLAMA_MODEL
    options = _ollama_options()
    payload: Dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "options": options,
    }
    if system_prompt:
        payload["system"] = system_prompt

    url = _ollama_url("/api/generate")
    resp = _post_json(url, payload, timeout_s=timeout_s, stream=True)
    resp.raise_for_status()

    final_payload: Optional[Dict[str, Any]] = None
    try:
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("error"):
                raise RuntimeError(str(obj.get("error")))
            chunk = (obj.get("response") or "") if isinstance(obj.get("response"), str) else ""
            if chunk:
                yield chunk, None
            if bool(obj.get("done")):
                final_payload = obj
                break
    finally:
        resp.close()
    yield "", final_payload


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def infer(prompt: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
    """
    Run a single inference call against Ollama.

    Args:
        prompt: User prompt text.
        system_prompt: Optional system instruction.

    Returns:
        dict: {response, model, tokens_used, latency_ms, success}
    """
    text, model_used, tokens_used, latency_ms, ok = _infer_call(prompt=prompt, system_prompt=system_prompt)
    _STATS.record(latency_ms=latency_ms, tokens_used=tokens_used, success=ok)
    return {
        "response": text,
        "model": model_used,
        "tokens_used": tokens_used,
        "latency_ms": latency_ms,
        "success": ok,
    }


def infer_with_context(context: str, question: str) -> Dict[str, Any]:
    """
    Prepend context to a question and call infer().

    Args:
        context: Retrieved context (RAG snippets, DB summaries, etc.).
        question: The user question to be answered using the context.

    Returns:
        dict: {response, model, tokens_used, latency_ms, success}
    """
    combined = (
        "Use the following CONTEXT to answer the QUESTION.\n"
        "If the context is insufficient, say what is missing.\n\n"
        "<CONTEXT>\n"
        f"{context}\n"
        "</CONTEXT>\n\n"
        "<QUESTION>\n"
        f"{question}\n"
        "</QUESTION>\n"
    )
    return infer(combined)


def infer_json(prompt: str, schema_hint: str) -> Dict[str, Any]:
    """
    Instruct the model to return JSON and parse the result.

    Args:
        prompt: Prompt text describing what JSON to produce.
        schema_hint: A human-readable schema/shape hint (example JSON, fields list, etc.).

    Returns:
        dict: {data, raw, model, tokens_used, latency_ms, success}
        - data: parsed JSON object (or None)
        - raw: raw model output string
    """
    system_prompt = (
        "You are a JSON generator.\n"
        "Return ONLY valid JSON. No markdown, no commentary.\n"
        "Rules:\n"
        "- Use double quotes for all keys and string values.\n"
        "- Do not include trailing commas.\n"
        "- Do not wrap the JSON in ``` fences.\n\n"
        "Schema / shape hint:\n"
        f"{schema_hint}\n"
    )

    raw, model_used, tokens_used, latency_ms, api_ok = _infer_call(prompt=prompt, system_prompt=system_prompt)
    data, parse_ok = _parse_json_from_text(raw)
    ok = bool(api_ok and parse_ok)
    # Record *overall* success for JSON calls (API + parse).
    _STATS.record(latency_ms=latency_ms, tokens_used=tokens_used if api_ok else 0, success=ok)

    if not ok:
        if not api_ok:
            _LOG.warning("infer_json failed: Ollama call failed.")
        elif not parse_ok:
            _LOG.warning("infer_json failed: model did not return valid JSON.")

    return {
        "data": data if ok else None,
        "raw": raw,
        "model": model_used,
        "tokens_used": tokens_used if api_ok else 0,
        "latency_ms": latency_ms,
        "success": ok,
    }


def stream_infer(prompt: str) -> Generator[str, None, None]:
    """
    Stream response chunks as they arrive from Ollama.

    Notes:
        - Chunking is controlled by Ollama; this yields incremental text fragments.
        - Stats are recorded when the stream finishes (or errors).

    Yields:
        str: incremental response chunk(s)
    """
    start = time.perf_counter()
    tokens_used = 0
    model_used = OLLAMA_MODEL
    success = False
    final_seen = False
    last_err: Optional[BaseException] = None

    try:
        # Retry on TIMEOUT only, up to 3 attempts.
        for attempt in range(1, 4):
            try:
                # Prefer chat stream; fall back to generate stream if chat unavailable.
                try:
                    stream_iter = _stream_chat(prompt=prompt, system_prompt=None, timeout_s=float(AI_TIMEOUT))
                except _EndpointNotFound:
                    stream_iter = _stream_generate(prompt=prompt, system_prompt=None, timeout_s=float(AI_TIMEOUT))

                for chunk, final_payload in stream_iter:
                    if chunk:
                        yield chunk
                    if final_payload is not None:
                        final_seen = True
                        model_used = final_payload.get("model") or model_used
                        tokens_used = _extract_tokens_used(final_payload)
                        success = True
                break
            except requests.exceptions.Timeout as e:
                last_err = e
                _LOG.warning("Ollama stream timeout (attempt %s/3).", attempt)
                if attempt < 3:
                    time.sleep(0.25 * attempt)
                    continue
            except Exception as e:  # noqa: BLE001
                last_err = e
                _LOG.exception("Ollama stream failed.")
                break

        if not final_seen:
            # Stream ended without a final payload; treat as failure.
            success = False
    finally:
        latency_ms = int((time.perf_counter() - start) * 1000)
        _STATS.record(latency_ms=latency_ms, tokens_used=tokens_used if final_seen else 0, success=success)
        if last_err is not None:
            _LOG.debug("stream_infer end state: success=%s err=%r", success, last_err)
