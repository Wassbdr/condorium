"""LiteLLM calls, response caching and JSON parsing.

All model calls in the project go through `complete_json` / `complete_text`.
Tests replace `_completion` to run without network access or keys.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from contextlib import contextmanager
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import quote

from .config import SETTINGS

# Transient provider failures worth retrying, matched by exception class name
# so any LiteLLM provider (or a test double) qualifies without importing it.
_TRANSIENT_ERRORS = {
    "RateLimitError", "APIConnectionError", "ServiceUnavailableError",
    "Timeout", "APITimeoutError", "InternalServerError",
}

_MODEL_PARAMS = {
    "nvidia_nim/nvidia/nemotron-*": {
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    },
    "stepfun-ai/step-5-preview": {"reasoning_effort": "low"},
    "*/stepfun-ai/step-5-preview": {"reasoning_effort": "low"},
}


class UsageMeter:
    """Counts calls and tokens of every LLM call made while it is active.

    Providers report real usage (`record_usage`); when a seam (test double,
    replay) reports nothing, tokens are estimated at ~4 characters per token.
    """

    def __init__(self) -> None:
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.estimated = False
        self._lock = threading.Lock()

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, prompt_tokens: int, completion_tokens: int, estimated: bool = False) -> None:
        with self._lock:
            self.calls += 1
            self.prompt_tokens += int(prompt_tokens or 0)
            self.completion_tokens += int(completion_tokens or 0)
            self.estimated = self.estimated or estimated

    def as_dict(self) -> dict:
        return {"calls": self.calls, "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens, "estimated": self.estimated}


_meters: list[UsageMeter] = []
_meters_lock = threading.Lock()
_reported = threading.local()


@contextmanager
def usage_meter():
    meter = UsageMeter()
    with _meters_lock:
        _meters.append(meter)
    try:
        yield meter
    finally:
        with _meters_lock:
            _meters.remove(meter)


def record_usage(prompt_tokens: int, completion_tokens: int) -> None:
    """Called by `_completion` with the provider's real token counts."""
    _reported.usage = (prompt_tokens, completion_tokens)


class _Usage(NamedTuple):
    prompt_tokens: int
    completion_tokens: int
    estimated: bool


def _take_usage(messages: list[dict], reply: str) -> _Usage:
    usage = getattr(_reported, "usage", None)
    _reported.usage = None
    if usage is None:
        prompt_chars = sum(len(m.get("content") or "") for m in messages)
        return _Usage(prompt_chars // 4, len(reply) // 4, True)
    return _Usage(*usage, False)


def _account(usage: _Usage) -> None:
    with _meters_lock:
        meters = list(_meters)
    for meter in meters:
        meter.add(*usage)


class OfflineCacheMiss(RuntimeError):
    """The requested response was not recorded in the configured cache."""


_cache_lock = threading.Lock()
_cache: dict[Path, dict[str, dict[str, Any]]] = {}


def _request_key(request: dict[str, Any]) -> str:
    encoded = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _cached_response(path: Path, key: str) -> dict[str, Any] | None:
    with _cache_lock:
        if path not in _cache:
            entries = {}
            try:
                with path.open("rb") as fh:
                    for line in fh:
                        try:
                            entry = json.loads(line)
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            continue  # an interrupted write can leave an incomplete row
                        entries[entry["key"]] = entry
            except FileNotFoundError:
                pass
            _cache[path] = entries
        return _cache[path].get(key)


def _save_response(path: Path, key: str, model: str, response: str, usage: _Usage) -> None:
    entry = {"key": key, "response": response, "usage": usage._asdict(), "model": model}
    row = json.dumps(entry, ensure_ascii=False).encode("utf-8") + b"\n"
    with _cache_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as fh:
            if fh.tell():
                fh.seek(-1, os.SEEK_END)
                if fh.read(1) != b"\n":
                    row = b"\n" + row
            fh.write(row)
        _cache[path][key] = entry


def _provider_params(model: str, params: dict[str, Any]) -> dict[str, Any]:
    for pattern, defaults in _MODEL_PARAMS.items():
        if fnmatchcase(model, pattern):
            if "extra_body" in defaults and params.get("extra_body"):
                body = params["extra_body"]
                return {**params, "extra_body": {
                    **body,
                    "chat_template_kwargs": {
                        **(body.get("chat_template_kwargs") or {}),
                        **defaults["extra_body"]["chat_template_kwargs"],
                    },
                }}
            return {**params, **defaults}
    return params


def _completion(*, model: str, messages: list[dict], timeout: int, **kwargs: Any) -> str:
    """Single seam to the model provider."""
    import litellm

    if model.startswith("nvidia_nim/"):
        if ("api_key" not in kwargs and not os.environ.get("NVIDIA_NIM_API_KEY")
                and (key := os.environ.get("NIM_API_KEY"))):
            kwargs["api_key"] = key
        if "reasoning_effort" in kwargs:
            # LiteLLM's NIM adapter drops this field unless it comes through extra_body.
            kwargs["extra_body"] = {
                **(kwargs.get("extra_body") or {}),
                "reasoning_effort": kwargs.pop("reasoning_effort"),
            }
    resp = litellm.completion(model=model, messages=messages, timeout=timeout, **kwargs)
    if (usage := getattr(resp, "usage", None)) is not None:
        record_usage(getattr(usage, "prompt_tokens", 0), getattr(usage, "completion_tokens", 0))
    return resp.choices[0].message.content or ""


def _is_transient(exc: Exception) -> bool:
    return any(cls.__name__ in _TRANSIENT_ERRORS for cls in type(exc).__mro__)


class CallBudgetExceeded(RuntimeError):
    """Raised before a provider call once CONDORIUM_MAX_CALLS is spent."""


_calls_made = 0
_calls_lock = threading.Lock()


_next_slot = 0.0


def _spend_call() -> None:
    """Budget guard (CONDORIUM_MAX_CALLS), client-side pacing (CONDORIUM_RPM)
    and an optional append-only ledger of every attempt (CONDORIUM_CALL_LOG)."""
    global _calls_made, _next_slot
    limit = os.environ.get("CONDORIUM_MAX_CALLS")
    rpm = float(os.environ.get("CONDORIUM_RPM") or 15)
    with _calls_lock:
        if limit and _calls_made >= int(limit):
            raise CallBudgetExceeded(f"CONDORIUM_MAX_CALLS={limit} reached")
        if rpm > 0:
            wait = _next_slot - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            _next_slot = time.monotonic() + 60.0 / rpm
        else:
            _next_slot = 0.0
        _calls_made += 1
        if ledger := os.environ.get("CONDORIUM_CALL_LOG"):
            with open(ledger, "a", encoding="utf-8") as fh:
                fh.write(f"{time.time():.0f}\n")


def complete_text(
    system: str,
    user: str,
    *,
    model: str | None = None,
    timeout: int | None = None,
    temperature: float | None = None,
    seed: int | None = None,
    max_tokens: int | None = None,
    **provider_params: Any,
) -> str:
    """Return a model response, replaying it from `CONDORIUM_CACHE` if present."""
    attempts = SETTINGS.llm_retries + 1
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    model = model or SETTINGS.model
    seed = seed if seed is not None else SETTINGS.llm_seed
    request = {
        "model": model, "messages": messages, "timeout": timeout or SETTINGS.llm_timeout,
        "drop_params": True, **_provider_params(model, provider_params),
    }
    for name, value in (("seed", seed), ("temperature", temperature), ("max_tokens", max_tokens)):
        if value is not None:
            request[name] = value

    cache_dir = os.environ.get("CONDORIUM_CACHE")
    path = Path(cache_dir).resolve() / f"{quote(model, safe='')}.jsonl" if cache_dir else None
    key = _request_key(request) if path else ""
    if path and (entry := _cached_response(path, key)) is not None:
        _account(_Usage(**entry["usage"]))
        return entry["response"]
    if os.environ.get("CONDORIUM_OFFLINE") == "1":
        raise OfflineCacheMiss(
            f"No cached response for {model}. Set CONDORIUM_CACHE to a recorded cache, "
            "or unset CONDORIUM_OFFLINE and set NIM_API_KEY or NVIDIA_NIM_API_KEY for a live NIM run."
        )

    for attempt in range(attempts):
        try:
            _spend_call()
            _reported.usage = None
            reply = _completion(**request)
        except Exception as exc:
            if attempt == attempts - 1 or not _is_transient(exc):
                raise
            rate_limited = any(c.__name__ == "RateLimitError" for c in type(exc).__mro__)
            if rate_limited and (ledger := os.environ.get("CONDORIUM_CALL_LOG")):
                with open(ledger, "a", encoding="utf-8") as fh:
                    fh.write("429\n")  # rejected attempt, not a processed call
            time.sleep(min(300, 15 * 2**attempt) if rate_limited else 0.5 * (4**attempt))
        else:
            usage = _take_usage(messages, reply)
            if path:
                _save_response(path, key, model, reply, usage)
            _account(usage)
            return reply
    raise RuntimeError("unreachable")


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def parse_json(raw: str) -> dict | list:
    """Strip markdown fences and surrounding prose, then parse."""
    text = _FENCE_RE.sub("", raw).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost JSON object/array embedded in prose.
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start, end = text.find(open_c), text.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"unparseable JSON from model: {raw[:200]!r}")


def complete_json(
    system: str,
    user: str,
    *,
    model: str | None = None,
    timeout: int | None = None,
    temperature: float | None = None,
    seed: int | None = None,
    max_tokens: int | None = None,
    **provider_params: Any,
) -> dict | list:
    """Call the model expecting strict JSON; on parse failure, retry once."""
    options = dict(provider_params, model=model, timeout=timeout, temperature=temperature,
                   seed=seed, max_tokens=max_tokens)
    raw = complete_text(system, user, **options)
    try:
        return parse_json(raw)
    except ValueError:
        retry_user = (
            f"{user}\n\nYour previous reply was not valid JSON:\n{raw[:1500]}\n"
            "Reply again with ONLY the JSON object, no prose, no code fences."
        )
        return parse_json(complete_text(system, retry_user, **options))
