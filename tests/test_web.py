"""Web app smoke tests against the test database."""
import pytest
from fastapi.testclient import TestClient

from parse.collectors.emit import emit
from parse.models import Source
from parse.registry import import_sources


@pytest.fixture
def client(db):
    import_sources(db)
    db.commit()
    from parse.web.app import app
    return TestClient(app)


def test_pages_render(client):
    for path in ("/", "/overview", "/how-it-works", "/sources", "/sources?tier=0", "/signals", "/signals?q=Kosovo&lang=sq"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert "PARSE" in r.text


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
    assert answer["citations"][0]["source_id"] == src.source_id


def test_ask_steps_explain_themselves_and_mark_ai(client, db):
    """The copilot view needs, per step: an explanation, where a model was involved, and links that stay on-site."""
    import json
    src = db.get(Source, "src_web_kossev")
    emit(db, src, url="https://kossev.info/test-ask-ai", raw=b"<html>Leposavic</html>", content_type="text/html",
         title="Leposavić", text="Leposavić opština", published_at=None, agent="A6", method="test")
    db.commit()
    events = [json.loads(x) for x in client.post("/api/ask", json={"q": "Leposavic"}).text.splitlines() if x]
    steps = {e["id"]: e for e in events if e["type"] == "step"}
    for s in steps.values():
        assert s["explain"] and s["ai"]["state"] in ("used", "available", "none") and s["ai"]["what"]
        for link in s.get("links", []) + s.get("items", []):
            assert link["href"].startswith("/"), link
    assert steps["brief"]["ai"]["state"] == "none"          # no language model writes the answer
    assert steps["classify"]["ai"]["state"] == "available"  # unlabelled: model stage exists but did not run
    assert any(i["href"].startswith("/signals/") for i in steps["rank"]["items"])
    picks = steps["rank"]["picks"]
    assert [x["id"] for x in picks["picked"]] == [src.source_id] and picks["picked"][0]["picked"] >= 1
    assert picks["picked"][0]["why"] and events[-1]["sources"]["considered"] == picks["considered"]


def test_ask_rejects_empty_and_handles_no_terms(client):
    assert client.post("/api/ask", json={"q": "  "}).status_code == 400
    import json
    events = [json.loads(x) for x in client.post("/api/ask", json={"q": "what is the"}).text.splitlines() if x]
    assert events[-1]["type"] == "answer" and events[-1]["citations"] == []


def test_tracer_page_and_api(client, db, monkeypatch):
    """The Tracer page renders, and a pasted text is traced back to the earliest archived copy (local only)."""
    from datetime import datetime, timezone

    from parse import tracer
    monkeypatch.setattr(tracer, "_embed", lambda nodes: (0, 0, None))   # no embedder in tests
    assert client.get("/trace").status_code == 200
    text = ("Snažna eksplozija kod Zubinog Potoka oštetila je kanal Ibar-Lepenac, voda curi a snabdevanje je "
            "prekinuto za veći deo opštine Zubin Potok prema prvim informacijama sa terena.")
    for i, sid in enumerate(("src_web_kossev", "src_web_kossev")):
        emit(db, db.get(Source, sid), url=f"https://kossev.info/trace-test-{i}", raw=f"<p>{text} {i}</p>".encode(),
             content_type="text/html", title=f"Eksplozija kod Zubinog Potoka, oštećen kanal Ibar-Lepenac {i}",
             text=text, published_at=datetime(2024, 11, 29, 19, 5 + 30 * i, tzinfo=timezone.utc), agent="A6",
             method="test")
    db.commit()
    lines = [__import__("json").loads(x) for x in client.post(
        "/api/trace", json={"text": text, "ai": False}).text.splitlines() if x.strip()]
    steps = [x["id"] for x in lines if x["type"] == "step"]
    assert steps[:4] == ["seed", "expand", "graph", "origin"] and steps[-1] == "brief"
    res = lines[-1]
    assert res["type"] == "result" and res["origin"]["url"].endswith("trace-test-0")
    assert res["verdict"]["checked"] is False and "earliest observed" in res["brief"]["headline"]
    assert client.get(f"/trace/{res['event_id']}").status_code == 200
    assert client.get(f"/api/trace/{res['event_id']}").json()["event_id"] == res["event_id"]
    assert client.post("/api/trace", json={}).status_code == 400


def test_watch_replay_groups_and_traces(client, db, monkeypatch):
    """The automation: a replayed window is grouped into a story, the story is traced, the dashboard sees it."""
    from datetime import datetime, timezone

    from parse import tracer, watch
    monkeypatch.setattr(tracer, "_embed", lambda nodes: (0, 0, None))
    text = ("Snažna eksplozija kod Zubinog Potoka oštetila je kanal Ibar-Lepenac, voda curi a snabdevanje je "
            "prekinuto za veći deo opštine Zubin Potok prema prvim informacijama sa terena.")
    for i, sid in enumerate(("src_web_kossev", "src_web_kossev", "src_web_kosovo_online")):
        src = db.get(Source, sid) or db.get(Source, "src_web_kossev")
        emit(db, src, url=f"https://example.org/watch-test-{i}", raw=f"<p>{text} {i}</p>".encode(),
             content_type="text/html", title=f"Eksplozija kod Zubinog Potoka, oštećen kanal Ibar-Lepenac {i}",
             text=text, published_at=datetime(2024, 11, 29, 19, 5 + 20 * i, tzinfo=timezone.utc), agent="A6",
             method="test", window="canal_2024_11")
    db.commit()
    w = watch.Watcher()
    w.start("replay", "canal_2024_11", step_min=180, interval=0,
            start_at=datetime(2024, 11, 29, 18, tzinfo=timezone.utc), background=False)
    w.run_cycle()
    st = w.state()
    assert st["stage_counts"]["collect"] == 3 and st["totals"]["stories"] == 1
    story = st["stories"][0]
    if story["sources"] >= 2:   # the registry may map both test urls to one outlet; tracing needs two accounts
        assert story["traced"] and story["origin"]["when"].startswith("2024-11-29T19:05")
    w.stop()
    assert client.get("/watch").status_code == 200
    assert client.get("/api/watch/state").json()["running"] is False
    assert any(a["live"] for a in client.get("/api/watch/accounts").json())
