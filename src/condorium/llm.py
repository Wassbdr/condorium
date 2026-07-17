"""LiteLLM wrapper with robust JSON parsing.

All model calls in the project go through `complete_json` / `complete_text`.
Tests (and `panel demo`) replace `_completion` — no network, no keys.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from .config import SETTINGS

# Transient provider failures worth retrying, matched by exception class name
# so any LiteLLM provider (or a test double) qualifies without importing it.
_TRANSIENT_ERRORS = {
    "RateLimitError", "APIConnectionError", "ServiceUnavailableError",
    "Timeout", "APITimeoutError", "InternalServerError",
}


def _completion(*, model: str, messages: list[dict], timeout: int, **kwargs: Any) -> str:
    """Single seam to the model provider. Monkeypatched in tests/demo."""
    import litellm

    resp = litellm.completion(model=model, messages=messages, timeout=timeout, **kwargs)
    return resp.choices[0].message.content or ""


def _is_transient(exc: Exception) -> bool:
    return any(cls.__name__ in _TRANSIENT_ERRORS for cls in type(exc).__mro__)


def complete_text(system: str, user: str, *, model: str | None = None, timeout: int | None = None) -> str:
    attempts = SETTINGS.llm_retries + 1
    for attempt in range(attempts):
        try:
            return _completion(
                model=model or SETTINGS.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                timeout=timeout or SETTINGS.llm_timeout,
            )
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
) -> dict | list:
    """Call the model expecting strict JSON; on parse failure, retry once."""
    raw = complete_text(system, user, model=model, timeout=timeout)
    try:
        return parse_json(raw)
    except ValueError:
        retry_user = (
            f"{user}\n\nYour previous reply was not valid JSON:\n{raw[:1500]}\n"
            "Reply again with ONLY the JSON object, no prose, no code fences."
        )
        return parse_json(complete_text(system, retry_user, model=model, timeout=timeout))
