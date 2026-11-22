"""Featherless AI client (OpenAI-compatible chat, /v1/classifier, /v1/embeddings) plus the local embedder.

Every paid call: checks the budget first, records the settled cost to the spend ledger, and the caller
stores the output with its prompt version (atlas.models.LlmOutput).
"""
from __future__ import annotations

import base64
import json
import os
import threading
import time
from functools import lru_cache

import httpx
from pydantic import BaseModel, ValidationError

from atlas import budget


class MissingApiKey(RuntimeError):
    pass


class RateLimiter:
    """Sliding one-minute window shared by every Featherless call in this process. A call over the limit waits
    for the oldest call in the window to age out instead of failing."""

    def __init__(self, per_minute: int):
        self.per_minute = max(1, int(per_minute))
        self._calls: list[float] = []
        self._lock = threading.Lock()

    def wait(self) -> float:
        waited = 0.0
        while True:
            with self._lock:
                now = time.monotonic()
                self._calls = [t for t in self._calls if now - t < 60]
                if len(self._calls) < self.per_minute:
                    self._calls.append(now)
                    return waited
                pause = 60 - (now - self._calls[0]) + 0.05
            time.sleep(pause)
            waited += pause


@lru_cache
def rate_limiter() -> RateLimiter:
    return RateLimiter(budget.models_cfg()["featherless"].get("requests_per_minute", 40))


class Featherless:
    def __init__(self, api_key: str | None = None, transport: httpx.BaseTransport | None = None):
        cfg = budget.models_cfg()["featherless"]
        key = api_key or os.environ.get("FEATHERLESS_API_KEY")
        if not key:
            raise MissingApiKey("Set FEATHERLESS_API_KEY in .env (never commit it).")
        self.client = httpx.Client(base_url=cfg["base_url"], timeout=cfg["timeout_s"], transport=transport,
                                   headers={"Authorization": f"Bearer {key}"})
        self._sem = threading.Semaphore(cfg["max_concurrency"])

    def _post(self, path: str, body: dict, tries: int = 4) -> dict:
        with self._sem:
            for attempt in range(tries):
                rate_limiter().wait()
                r = self.client.post(path, json=body)
                if r.status_code in (429, 503) and attempt < tries - 1:  # concurrency limit / model warming up
                    time.sleep(5 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r.json()
        raise RuntimeError("unreachable")

    def _settle(self, role: str, stage: str, data: dict, note: str = "") -> tuple[int, int, float]:
        u = data.get("usage") or {}
        tin = int(u.get("prompt_tokens") or u.get("input_tokens") or 0)
        tout = int(u.get("completion_tokens") or u.get("output_tokens") or 0)
        usd = float(u["cost"]) if u.get("cost") is not None else budget.cost(role, tin, tout)
        budget.record(stage, budget.model(role)["id"], tin, tout, usd, note)
        return tin, tout, usd

    # ---------------------------------------------------------------- chat (JSON validated by pydantic)
    def chat_json(self, role: str, stage: str, system: str, user: str | list, schema: type[BaseModel],
                  max_tokens: int = 800, retries: int = 1) -> tuple[BaseModel, dict]:
        """Featherless chat has no structured-output mode, so we ask for JSON, validate it against
        `schema`, and retry once with the validation error appended."""
        budget.check(0.0)
        m = budget.model(role)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        last_err = None
        for _ in range(retries + 1):
            body = {"model": m["id"], "messages": messages, "temperature": 0, "max_tokens": max_tokens}
            if "enable_thinking" in m:
                body["chat_template_kwargs"] = {"enable_thinking": m["enable_thinking"]}
            data = self._post("/chat/completions", body)
            tin, tout, usd = self._settle(role, stage, data)
            text = data["choices"][0]["message"].get("content") or ""
            try:
                return schema.model_validate_json(_extract_json(text)), {"in": tin, "out": tout, "usd": usd}
            except (ValidationError, ValueError) as e:
                last_err = e
                messages = messages + [{"role": "assistant", "content": text},
                                       {"role": "user", "content": f"That was not valid JSON for the schema: {e}. "
                                                                   "Reply with the corrected JSON object only."}]
        raise ValueError(f"model did not return valid JSON: {last_err}")

    def chat_text(self, role: str, stage: str, system: str, user: str, max_tokens: int = 800) -> tuple[str, dict]:
        budget.check(0.0)
        m = budget.model(role)
        body = {"model": m["id"], "temperature": 0, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if "enable_thinking" in m:
            body["chat_template_kwargs"] = {"enable_thinking": m["enable_thinking"]}
        data = self._post("/chat/completions", body)
        tin, tout, usd = self._settle(role, stage, data)
        return data["choices"][0]["message"].get("content") or "", {"in": tin, "out": tout, "usd": usd}

    # ---------------------------------------------------------------- /v1/classifier (probabilities)
    def classify(self, role: str, stage: str, text: str, questions: dict, tries: int = 4) -> tuple[dict, dict]:
        """Returns {question_id: answer}. noul answers carry a probability in 0.01..0.99; choice answers
        carry a probability per option. Only input tokens are billed."""
        budget.check(0.0)
        data = self._post("/classifier", {"model": budget.model(role)["id"],
                                          "messages": [{"role": "user", "content": text}],
                                          "questions": questions}, tries=tries)
        tin, tout, usd = self._settle(role, stage, data)
        return data["answers"], {"in": tin, "out": tout, "usd": usd}

    # ---------------------------------------------------------------- vision OCR
    def ocr_image(self, role: str, stage: str, image_bytes: bytes, mime: str = "image/jpeg") -> tuple[str, dict]:
        budget.check(0.0)
        b64 = base64.b64encode(image_bytes).decode()
        content = [{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}]
        data = self._post("/chat/completions", {"model": budget.model(role)["id"], "temperature": 0,
                                                "max_tokens": 1500,
                                                "messages": [{"role": "user", "content": content}]})
        tin, tout, usd = self._settle(role, stage, data)
        return data["choices"][0]["message"].get("content") or "", {"in": tin, "out": tout, "usd": usd}

    def embed(self, role: str, stage: str, texts: list[str]) -> list[list[float]]:
        budget.check(0.0)
        data = self._post("/embeddings", {"model": budget.model(role)["id"], "input": texts})
        self._settle(role, stage, data)
        return [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]


def _extract_json(text: str) -> str:
    """Strip code fences or stray prose around the first JSON object."""
    t = text.strip()
    if "<think>" in t:  # thinking left on by the template
        t = t.split("</think>")[-1].strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in reply")
    json.loads(t[start:end + 1])
    return t[start:end + 1]


# ---------------------------------------------------------------- local embeddings (free)
@lru_cache
def _local_embedder():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(budget.model("embedding")["id"])


def embed_texts(texts: list[str], is_query: bool = False) -> list[list[float]]:
    m = budget.model("embedding")
    if m["provider"] == "local":
        model = _local_embedder()
        kw = {"prompt_name": "query"} if is_query else {}
        return model.encode(texts, normalize_embeddings=True, batch_size=16, **kw).tolist()
    return Featherless().embed("embedding", "embed", texts)
