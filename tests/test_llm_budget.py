"""Featherless client and budget gate, against a fake HTTP server: no network, no credits."""
import json

import httpx
import pytest

from atlas import budget
from atlas.detect import parse, questions
from atlas.label_teacher import TeacherLabel
from atlas.llm import Featherless, MissingApiKey, _extract_json


@pytest.fixture(autouse=True)
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "LEDGER", tmp_path / "ledger.csv")


def fake(handler):
    return Featherless(api_key="test-key", transport=httpx.MockTransport(handler))


def test_missing_key(monkeypatch):
    monkeypatch.delenv("FEATHERLESS_API_KEY", raising=False)
    with pytest.raises(MissingApiKey):
        Featherless()


def test_budget_gate_and_cost_from_config():
    assert budget.cost("teacher", 1_000_000, 1_000_000) == pytest.approx(0.117 + 0.455)
    budget.record("t", "m", 0, 0, budget.total_budget() - 0.5)
    budget.check(0.4)
    with pytest.raises(budget.BudgetExceeded):
        budget.check(0.6)


def test_classifier_returns_probabilities_and_records_settled_cost():
    seen = {}

    def handler(req: httpx.Request):
        body = json.loads(req.content)
        seen.update(body)
        assert req.headers["authorization"] == "Bearer test-key" and req.url.path == "/v1/classifier"
        answers = {k: {"type": "noul", "noul": 0.9 if k == "T4" else 0.05} for k in body["questions"]}
        return httpx.Response(200, json={"answers": answers, "usage": {"input_tokens": 900, "output_tokens": 3,
                                                                       "cost": 0.000027}})

    fl = fake(handler)
    answers, usage = fl.classify("detector", "detect", "post", questions())
    probs = parse(answers)
    assert seen["model"] == "featherless-ai/Qwen3.5-4B-classifier"
    assert set(probs) == {f"T{i}" for i in range(1, 11)} | {f"N{i}" for i in range(1, 12)} | {"offline_intent"}
    assert probs["T4"] == 0.9 and usage["usd"] == pytest.approx(0.000027)
    assert budget.spent() == pytest.approx(0.000027)


def test_chat_json_retries_once_on_invalid_json_and_disables_thinking():
    calls = []
    good = {"is_threat_relevant": True, "labels": ["T4"], "narratives": ["N2"],
            "offline_intent": {"present": False, "span": ""}, "places": ["Zvečan"], "orgs": []}

    def handler(req):
        body = json.loads(req.content)
        calls.append(body)
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        content = "Sure! here you go" if len(calls) == 1 else "```json\n" + json.dumps(good) + "\n```"
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}],
                                         "usage": {"prompt_tokens": 1000, "completion_tokens": 50}})

    out, usage = fake(handler).chat_json("teacher", "teacher-label", "sys", "post", TeacherLabel)
    assert out.labels == ["T4"] and len(calls) == 2
    # No `cost` in usage -> priced from config/models.yaml.
    assert budget.spent() == pytest.approx(2 * budget.cost("teacher", 1000, 50), abs=1e-6)


def test_chat_json_rejects_unknown_labels():
    bad = {"is_threat_relevant": True, "labels": ["T99"], "narratives": [],
           "offline_intent": {"present": False, "span": ""}, "places": [], "orgs": []}
    handler = lambda req: httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(bad)}}],
                                                    "usage": {"prompt_tokens": 10, "completion_tokens": 10}})
    with pytest.raises(ValueError, match="valid JSON"):
        fake(handler).chat_json("teacher", "t", "sys", "post", TeacherLabel)


def test_retry_on_429_then_success(monkeypatch):
    monkeypatch.setattr("atlas.llm.time.sleep", lambda s: None)
    n = {"i": 0}

    def handler(req):
        n["i"] += 1
        if n["i"] == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}], "usage": {}})

    text, _ = fake(handler).chat_text("translation", "translate", "sys", "zdravo")
    assert text == "hello" and n["i"] == 2


def test_extract_json_strips_think_block_and_fences():
    assert json.loads(_extract_json('<think>hmm</think>\n```json\n{"a": 1}\n```')) == {"a": 1}
    with pytest.raises(ValueError):
        _extract_json("no json here")
