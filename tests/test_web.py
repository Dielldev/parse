"""Web app smoke tests against the test database."""
import pytest
from fastapi.testclient import TestClient

from atlas.collectors.emit import emit
from atlas.models import Source
from atlas.registry import import_sources


@pytest.fixture
def client(db):
    import_sources(db)
    db.commit()
    from atlas.web.app import app
    return TestClient(app)


def test_pages_render(client):
    for path in ("/", "/overview", "/how-it-works", "/sources", "/sources?tier=0", "/signals", "/signals?q=Kosovo&lang=sq"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert "ATLAS" in r.text


def test_signal_detail_and_evidence_served_as_plain_text(client, db, tmp_path, monkeypatch):
    src = db.get(Source, "src_web_kossev")
    sig = emit(db, src, url="https://kossev.info/test-web", raw=b"<html><script>alert(1)</script>Zvecan</html>",
               content_type="text/html", title="Test Zvečan", text="Kosovo test text about Zvečan.",
               published_at=None, agent="A6", method="test")
    db.commit()
    r = client.get(f"/signals/{sig.signal_id}")
    assert r.status_code == 200 and "Test Zvečan" in r.text and "file matches hash" in r.text
    raw = client.get(f"/evidence/{sig.evidence_sha256}/raw")
    assert raw.headers["content-type"].startswith("text/plain") and raw.headers["x-content-type-options"] == "nosniff"
    assert client.get("/signals/sig_does_not_exist").status_code == 404


def test_tps_api_uses_pipeline_logic(client):
    r = client.post("/api/tps", json={"severity": 1, "velocity": 1, "reach": 1, "coordination": 1,
                                      "offline_intent": 1, "proximity": 1, "best_tier": "0"}).json()
    assert r["tps"] == 100 and r["priority"] == "P1"
    r = client.post("/api/tps", json={"severity": 0.1, "best_tier": "3", "tripwires": ["dox"]}).json()
    assert r["priority"] == "P1" and "Tripwire" in r["explanation"]


def test_verdict_api_counts_origin_groups_once(client):
    same = [{"stance": "supports", "tier": 1, "origin": "tg_A"}, {"stance": "supports", "tier": 1, "origin": "tg_A"}]
    assert client.post("/api/verdict", json={"evidence": same}).json()["verdict"] == "UNVERIFIED"
    two = [{"stance": "supports", "tier": 1, "origin": "a"}, {"stance": "supports", "tier": 2, "origin": "b"}]
    assert client.post("/api/verdict", json={"evidence": two}).json()["verdict"] == "CORROBORATED"


def test_ask_streams_workflow_steps(client, db):
    import json
    src = db.get(Source, "src_web_kossev")
    emit(db, src, url="https://kossev.info/test-ask", raw=b"<html>Zve\xc4\x8dan bridge</html>", content_type="text/html",
         title="Okupljanje kod mosta u Zvečanu", text="Građani su se okupili kod mosta u Zvečanu.",
         published_at=None, agent="A6", method="test")
    db.commit()
    r = client.post("/api/ask", json={"q": "What happened in Zvecan?"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in r.text.splitlines() if line]
    steps = [e["id"] for e in events if e["type"] == "step"]
    assert steps == ["trigger", "normalise", "registry", "search", "sources", "rank", "evidence", "classify",
                     "spread", "brief"]
    answer = events[-1]
    assert answer["type"] == "answer" and answer["citations"][0]["source"] == src.name
    assert "Zvečan" in answer["citations"][0]["snippet"]   # unaccented query matched the accented text


def test_ask_rejects_empty_and_handles_no_terms(client):
    assert client.post("/api/ask", json={"q": "  "}).status_code == 400
    import json
    events = [json.loads(x) for x in client.post("/api/ask", json={"q": "what is the"}).text.splitlines() if x]
    assert events[-1]["type"] == "answer" and events[-1]["citations"] == []
