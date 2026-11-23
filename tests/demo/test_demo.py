"""Web-demo checks (the Vercel deployment). Run them on their own, they need demo mode before parse is imported:

    PARSE_DEMO=1 uv run python -m pytest tests/demo -q

They use the committed snapshot (demo/parse_demo.sqlite.gz) and never call Featherless.
"""
import os

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("PARSE_DEMO") != "1", reason="run with PARSE_DEMO=1")

if os.environ.get("PARSE_DEMO") == "1":
    from fastapi.testclient import TestClient

    from parse.web import demo as demo_mod
    from parse.web.app import app

    client = TestClient(app, base_url="https://parse.test")


@pytest.fixture(autouse=True)
def _fresh_limits():
    demo_mod._limiter._hits.clear()
    yield


def test_pages_render_from_snapshot():
    for path in ("/", "/overview", "/sources", "/signals?q=Banjska", "/how-it-works", "/trace", "/agents"):
        r = client.get(path)
        assert r.status_code == 200, path


def test_pipeline_only_routes_are_off():
    for path in ("/watch", "/evidence/" + "a" * 64 + "/raw", "/docs", "/openapi.json", "/api/watch/state"):
        assert client.get(path).status_code == 404, path


def test_live_agent_and_scout_routes_do_not_exist():
    # the browser scout, the field-agent dispatcher and their live feeds need outbound network: never mounted here
    for path in ("/api/scout/start", "/api/scout/status", "/api/agents/dispatch", "/api/agents/discord/channels"):
        assert client.post(path, json={}).status_code == 404, path
    assert client.get("/api/scout/status").status_code == 404


def test_security_headers_and_nonce_csp():
    r = client.get("/")
    csp = r.headers["content-security-policy"]
    assert "script-src 'self' 'nonce-" in csp and "'unsafe-inline'" not in csp.split("style-src")[0]
    assert "frame-ancestors 'none'" in csp and "connect-src 'self'" in csp
    nonce = csp.split("'nonce-")[1].split("'")[0]
    assert f'nonce="{nonce}"' in r.text            # inline scripts carry this request's nonce
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cache-control"] == "no-store"
    assert "max-age" in r.headers["strict-transport-security"]


def test_static_files_are_cacheable_and_key_js_is_served():
    r = client.get("/static/key.js")
    assert r.status_code == 200 and "public" in r.headers["cache-control"]


def test_oversized_body_and_odd_methods_are_refused():
    assert client.post("/api/ask", content=b"x" * 60_000).status_code == 413
    assert client.delete("/api/ask").status_code == 405


def test_rate_limit_kicks_in():
    codes = [client.post("/api/tps", json={}).status_code for _ in range(demo_mod.PER_MINUTE_API_POST + 5)]
    assert codes[0] == 200 and codes[-1] == 429


def test_models_need_the_visitors_key():
    import sqlalchemy as sa

    from parse.db import session
    from parse.models import Signal
    with session() as db:
        sid = db.scalar(sa.select(Signal.signal_id).limit(1))
    r = client.post(f"/api/signals/{sid}/model/label", json={})
    assert r.status_code == 400 and "key" in r.json()["detail"].lower()
    assert client.post("/api/key/check").status_code == 400


def test_malformed_key_is_ignored_not_forwarded():
    r = client.post("/api/key/check", headers={"X-Featherless-Key": "short key with spaces"})
    assert r.status_code == 400 and r.json()["detail"] == "No key received."


def test_key_is_only_honoured_on_model_routes():
    from parse.web.models_live import request_key
    seen = {}

    @app.get("/__probe_key")
    def probe():
        seen["key"] = request_key.get()
        return {}
    good = "abcdefghijklmnopqrstuvwxyz0123456789"
    client.get("/__probe_key", headers={"X-Featherless-Key": good})
    assert seen["key"] is None            # not a model route: the header is dropped
    assert request_key.get() is None      # and nothing leaks past the request


def test_trace_refuses_links_and_screenshots():
    r = client.post("/api/trace", json={"url": "http://169.254.169.254/latest/meta-data"})
    assert r.status_code == 400
    r = client.post("/api/trace", json={"image": "data:image/png;base64,AAAA"})
    assert r.status_code == 400


def test_ask_answers_without_any_key():
    r = client.post("/api/ask", json={"q": "What happened at Banjska?"})
    assert r.status_code == 200
    events = [__import__("json").loads(line) for line in r.text.splitlines()]
    assert events[-1]["type"] == "answer" and events[-1]["citations"]


def test_trace_runs_on_pasted_text_and_saves_nothing():
    r = client.post("/api/trace", json={"text": "Shpërthim në Zubin-Potok, dëmtohet kanali i ujit të Ibër-Lepencit"})
    events = [__import__("json").loads(line) for line in r.text.splitlines()]
    result = events[-1]
    assert result["type"] == "result" and result["tps"]["priority"] in ("P1", "P2", "P3", "P4")
    assert "event_id" not in result and result["verdict"]["checked"] is False


def test_writes_are_dropped_and_the_file_is_read_only():
    import sqlalchemy as sa

    from parse.db import engine, session
    from parse.models import Signal
    with session() as s:
        before = s.scalar(sa.select(sa.func.count()).select_from(Signal))
        s.add(Signal(signal_id="sig_test", platform="news", source_id="x", url="u"))
        s.flush()          # pending writes are discarded instead of raising
    with session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(Signal)) == before
    with engine.connect() as c, pytest.raises(sa.exc.OperationalError):
        c.execute(sa.text("DELETE FROM signal"))


def test_snapshot_has_no_embeddings_or_server_secrets():
    import sqlalchemy as sa

    from parse.db import engine
    with engine.connect() as c:
        assert c.scalar(sa.text("SELECT count(*) FROM signal WHERE embedding IS NOT NULL")) == 0
        assert c.scalar(sa.text("SELECT count(*) FROM signal WHERE length(text_original) > 1300")) == 0


def _replay(**body):
    r = client.post("/api/agents/replay", json=body)
    return r, ([__import__("json").loads(x) for x in r.text.splitlines() if x] if r.status_code == 200 else [])


def test_agents_page_is_a_replay_with_no_key_and_no_live_agent_code():
    import sys
    r = client.get("/agents")
    assert r.status_code == 200 and "This is a replay" in r.text and "window.REPLAY = true" in r.text
    nonce = r.headers["content-security-policy"].split("'nonce-")[1].split("'")[0]
    assert f'nonce="{nonce}"' in r.text
    # nothing that fetches or drives a browser is even imported in demo mode
    for mod in ("parse.agents.runner", "parse.agents.scout", "parse.agents.methods", "playwright", "trafilatura", "feedparser"):
        assert mod not in sys.modules, mod


def test_telegram_replay_streams_recorded_posts():
    r, ev = _replay(platform="telegram", target="@balkanspectator", topic="Kosovo", limit=3)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    kinds = [e["t"] for e in ev]
    assert kinds[0] == "start" and kinds[-1] == "end" and ev[0]["replay"] is True
    posts = [e for e in ev if e["t"] == "post"]
    assert posts and all(p["signal_id"] and p["matched"] for p in posts) and len(posts) <= 3
    assert ev[-1]["kept"] == ev[-1]["matched"] == len(posts)


def test_news_replay_reports_archived_items_per_site():
    r, ev = _replay(platform="web", sources=["src_web_n1", "src_web_kosovo_online"], topic="Banjska", limit=2)
    assert r.status_code == 200
    items = [e for e in ev if e["t"] == "item"]
    assert items and all(i["id"].startswith("sig_") for i in items)
    done = [e for e in ev if e["t"] == "source" and e["state"] == "done"]
    assert {d["source"] for d in done} == {"src_web_n1", "src_web_kosovo_online"}
    assert ev[-1]["t"] == "end" and ev[-1]["kept"] == len(items)


def test_login_only_platforms_say_so_instead_of_pretending():
    r, ev = _replay(platform="x", target="@NATO_KFOR", topic="", limit=5)
    assert r.status_code == 200
    assert any(e["t"] == "target" and e["state"] == "login" for e in ev)
    assert ev[-1]["read"] == 0


def test_replay_rejects_bad_input():
    assert _replay(platform="evil")[0].status_code == 400
    assert _replay(platform="telegram", limit="many")[0].status_code == 400
    assert _replay(platform="web", sources=[])[0].status_code == 400
    assert client.post("/api/agents/replay", content=b"[1]", headers={"content-type": "application/json"}).status_code == 400
    assert client.post("/api/agents/replay", content=b"nope", headers={"content-type": "application/json"}).status_code == 400


def test_replay_clamps_long_text_and_never_echoes_a_url_it_fetched():
    r, ev = _replay(platform="telegram", target="https://evil.example/x" + "a" * 500, topic="q" * 5000, limit=999)
    # an unrelated host is just text to the handle parser: it never becomes a request
    assert r.status_code in (200, 400)
    if r.status_code == 200:
        assert len(ev[0]["topic"]) <= 200 and all("evil.example" not in str(e.get("url", "")) for e in ev)
