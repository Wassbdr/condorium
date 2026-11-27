import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from openai import OpenAI

from condorium import llm

NEMOTRON = "nvidia_nim/nvidia/nemotron-3.5-lightning-30b-a3b"
SUPER_VL = "nvidia_nim/nvidia/nemotron-3.5-super-vl-120b-a12b"
STEP = "nvidia_nim/stepfun-ai/step-5-preview"


@pytest.fixture
def cache(tmp_path, monkeypatch):
    path = tmp_path / "cache"
    monkeypatch.setenv("CONDORIUM_CACHE", str(path))
    monkeypatch.setattr(llm, "_cache", {})
    return path


@pytest.fixture
def completion(monkeypatch):
    requests = []

    def complete(**request):
        requests.append(request)
        llm.record_usage(17, 41)
        return '{"ok": true}'

    monkeypatch.setattr(llm, "_completion", complete)
    return requests


def test_disk_replay_uses_same_usage_without_pacing(cache, completion, monkeypatch):
    with llm.usage_meter() as live:
        assert llm.complete_text("system message", "private abstract", model=NEMOTRON)
    [path] = cache.glob("*.jsonl")
    stored = path.read_text()
    assert "system message" not in stored and "private abstract" not in stored
    entry = json.loads(stored)
    assert set(entry) == {"key", "response", "usage", "model"}
    assert len(entry["key"]) == 64 and entry["model"] == NEMOTRON
    assert entry["usage"] == {"prompt_tokens": 17, "completion_tokens": 41, "estimated": False}
    assert len(completion) == 1

    llm._cache.clear()
    monkeypatch.setenv("CONDORIUM_OFFLINE", "1")
    monkeypatch.setattr(llm, "_spend_call", lambda: pytest.fail("cache replay was paced"))
    with llm.usage_meter() as replay:
        assert llm.complete_text("system message", "private abstract", model=NEMOTRON)
    assert live.as_dict() == replay.as_dict()
    assert path.read_text() == stored
    assert len(completion) == 1


def test_offline_miss_names_model_and_live_credentials(cache, completion, monkeypatch):
    monkeypatch.setenv("CONDORIUM_OFFLINE", "1")
    monkeypatch.setattr(llm, "_spend_call", lambda: pytest.fail("offline miss was paced"))
    with pytest.raises(llm.OfflineCacheMiss, match=f"{STEP}.*NIM_API_KEY.*NVIDIA_NIM_API_KEY"):
        llm.complete_text("system", "user", model=STEP)
    assert not cache.exists()
    assert not completion


def test_key_is_order_independent_but_includes_provider_params(cache, completion):
    model = "provider/model"
    opts = {"model": model, "max_tokens": 25, "seed": 7, "temperature": 0.0}
    body = {"a": 1, "b": {"x": 2, "y": 3}}
    assert llm.complete_json("s", "u", **opts, extra_body=body, top_p=0.8) == {"ok": True}
    llm.complete_json("s", "u", **opts, top_p=0.8, extra_body={"b": {"y": 3, "x": 2}, "a": 1})
    assert len(completion) == 1
    for change in (
        {"extra_body": {"a": 2}}, {"top_p": 0.9},
        {"seed": 8}, {"temperature": 0.2}, {"max_tokens": 26},
    ):
        llm.complete_json("s", "u", **(opts | {"extra_body": body, "top_p": 0.8} | change))
    assert len(completion) == 6
    assert completion[0]["temperature"] == 0.0
    assert completion[0]["seed"] == 7
    assert completion[0]["max_tokens"] == 25


def test_presets_are_forwarded_and_hashed(cache, completion, monkeypatch):
    body = {"marker": "keep", "chat_template_kwargs": {"enable_thinking": True, "other": 1}}
    llm.complete_text("s", "u", model=NEMOTRON, extra_body=body)
    assert completion[0]["extra_body"] == {
        "marker": "keep", "chat_template_kwargs": {"enable_thinking": False, "other": 1},
    }
    llm.complete_text("s", "u", model=STEP)
    assert completion[1]["reasoning_effort"] == "low"
    monkeypatch.setitem(llm._MODEL_PARAMS, "*/stepfun-ai/step-5-preview",
                        {"reasoning_effort": "medium"})
    llm.complete_text("s", "u", model=STEP)
    assert completion[2]["reasoning_effort"] == "medium"
    assert len(list(cache.glob("*.jsonl"))) == 2


def test_super_vl_thinking_preset_changes_request_key(cache, completion, monkeypatch):
    llm.complete_text("s", "u", model=SUPER_VL)
    llm.complete_text("s", "u", model=SUPER_VL)
    assert len(completion) == 1
    assert completion[0]["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}

    monkeypatch.setitem(llm._MODEL_PARAMS, "nvidia_nim/nvidia/nemotron-*",
                        {"extra_body": {"chat_template_kwargs": {"enable_thinking": True}}})
    llm.complete_text("s", "u", model=SUPER_VL)
    assert len(completion) == 2
    [path] = cache.glob("*.jsonl")
    entries = [json.loads(line) for line in path.read_text().splitlines()]
    assert len({entry["key"] for entry in entries}) == 2


def test_nim_sends_step_reasoning_effort_and_keeps_reasoning_usage(monkeypatch):
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    monkeypatch.setenv("NIM_API_KEY", "test")
    monkeypatch.delenv("NVIDIA_NIM_API_KEY", raising=False)
    import litellm

    def capture(request):
        body = json.loads(request.content)
        assert body["reasoning_effort"] == "low"
        return httpx.Response(200, json={
            "id": "stub", "object": "chat.completion", "created": 1, "model": body["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 13, "completion_tokens": 41, "total_tokens": 54,
                      "completion_tokens_details": {"reasoning_tokens": 37}},
        })

    complete = litellm.completion
    with OpenAI(api_key="test", base_url="https://integrate.api.nvidia.com/v1",
                http_client=httpx.Client(transport=httpx.MockTransport(capture))) as client:
        def local_completion(**kwargs):
            assert kwargs["api_key"] == "test"
            return complete(client=client, **kwargs)

        monkeypatch.setattr(litellm, "completion", local_completion)
        with llm.usage_meter() as meter:
            assert llm.complete_text("s", "u", model=STEP) == "OK"
    assert meter.total_tokens == 54
    assert meter.completion_tokens == 41


def test_append_and_replay_after_incomplete_row(cache, completion):
    llm.complete_text("s", "old", model=STEP)
    [path] = cache.glob("*.jsonl")
    with path.open("ab") as fh:
        fh.write(b'{"key":')
    llm._cache.clear()
    llm.complete_text("s", "old", model=STEP)
    llm.complete_text("s", "new", model=STEP)
    llm._cache.clear()
    llm.complete_text("s", "new", model=STEP)
    assert len(completion) == 2


def test_default_pacing_and_appends_are_shared_by_threads(cache, completion, monkeypatch):
    now, waits = 10.0, []

    def sleep(delay):
        nonlocal now
        waits.append(delay)
        now += delay

    monkeypatch.delenv("CONDORIUM_RPM")
    monkeypatch.setattr(llm, "_next_slot", 0.0)
    monkeypatch.setattr(llm.time, "monotonic", lambda: now)
    monkeypatch.setattr(llm.time, "sleep", sleep)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda user: llm.complete_text("s", user, model=STEP), "abc"))
    assert waits == [4.0, 4.0]
    [path] = cache.glob("*.jsonl")
    assert len({json.loads(line)["key"] for line in path.read_text().splitlines()}) == 3
    assert len(completion) == 3
