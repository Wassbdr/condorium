"""LiteLLM wrapper with robust JSON parsing.

All model calls in the project go through `complete_json` / `complete_text`.
Tests (and `panel demo`) replace `_completion` — no network, no keys.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from contextlib import contextmanager
from typing import Any

from .config import SETTINGS

# Transient provider failures worth retrying, matched by exception class name
# so any LiteLLM provider (or a test double) qualifies without importing it.
_TRANSIENT_ERRORS = {
    "RateLimitError", "APIConnectionError", "ServiceUnavailableError",
    "Timeout", "APITimeoutError", "InternalServerError",
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


def _account(messages: list[dict], reply: str) -> None:
    usage = getattr(_reported, "usage", None)
    _reported.usage = None
    if usage is None:
        prompt_chars = sum(len(m.get("content") or "") for m in messages)
        usage, estimated = (prompt_chars // 4, len(reply) // 4), True
    else:
        estimated = False
    with _meters_lock:
        meters = list(_meters)
    for meter in meters:
        meter.add(*usage, estimated=estimated)


def _completion(*, model: str, messages: list[dict], timeout: int, **kwargs: Any) -> str:
    """Single seam to the model provider. Monkeypatched in tests/demo."""
    import litellm

    resp = litellm.completion(model=model, messages=messages, timeout=timeout,
                              drop_params=True, **kwargs)
    if (usage := getattr(resp, "usage", None)) is not None:
        record_usage(getattr(usage, "prompt_tokens", 0), getattr(usage, "completion_tokens", 0))
    return resp.choices[0].message.content or ""


def _is_transient(exc: Exception) -> bool:
    return any(cls.__name__ in _TRANSIENT_ERRORS for cls in type(exc).__mro__)


class CallBudgetExceeded(RuntimeError):
    """Raised before a provider call once CONDORIUM_MAX_CALLS is spent."""


_calls_made = 0
_calls_lock = threading.Lock()


def _spend_call() -> None:
    global _calls_made
    limit = os.environ.get("CONDORIUM_MAX_CALLS")
    with _calls_lock:
        if limit and _calls_made >= int(limit):
            raise CallBudgetExceeded(f"CONDORIUM_MAX_CALLS={limit} reached")
        _calls_made += 1


def complete_text(system: str, user: str, *, model: str | None = None, timeout: int | None = None,
                  seed: int | None = None) -> str:
    attempts = SETTINGS.llm_retries + 1
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    seed = seed if seed is not None else SETTINGS.llm_seed
    extra = {"seed": seed} if seed is not None else {}
    for attempt in range(attempts):
        try:
            _spend_call()
            _reported.usage = None
            reply = _completion(
                model=model or SETTINGS.model,
                messages=messages,
                timeout=timeout or SETTINGS.llm_timeout,
                **extra,
            )
            _account(messages, reply)
            return reply
        except Exception as exc:
            if attempt == attempts - 1 or not _is_transient(exc):
                raise
            time.sleep(0.5 * (4**attempt))  # 0.5s, 2s, ...
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
    seed: int | None = None,
) -> dict | list:
    """Call the model expecting strict JSON; on parse failure, retry once."""
    raw = complete_text(system, user, model=model, timeout=timeout, seed=seed)
    try:
        return parse_json(raw)
    except ValueError:
        retry_user = (
            f"{user}\n\nYour previous reply was not valid JSON:\n{raw[:1500]}\n"
            "Reply again with ONLY the JSON object, no prose, no code fences."
        )
        return parse_json(complete_text(system, retry_user, model=model, timeout=timeout,
                                        seed=seed))
