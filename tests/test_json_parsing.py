import json

import pytest

from condorium import llm


def test_strips_fences():
    assert llm.parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extracts_from_prose():
    assert llm.parse_json('Sure! Here it is: {"a": [1, 2]} hope that helps') == {"a": [1, 2]}


def test_unparseable_raises():
    with pytest.raises(ValueError):
        llm.parse_json("no json here at all")


def test_retries_once(monkeypatch):
    calls = []

    def fake(*, model, messages, timeout, **kw):
        calls.append(messages)
        return "garbage" if len(calls) == 1 else json.dumps({"ok": True})

    monkeypatch.setattr(llm, "_completion", fake)
    assert llm.complete_json("sys", "user") == {"ok": True}
    assert len(calls) == 2
    assert "not valid JSON" in calls[1][-1]["content"]
