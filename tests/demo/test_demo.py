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
    for path in ("/", "/overview", "/sources", "/signals?q=Banjska", "/how-it-works", "/trace"):
        r = client.get(path)
        assert r.status_code == 200, path


def test_pipeline_only_routes_are_off():
    for path in ("/watch", "/agents", "/evidence/" + "a" * 64 + "/raw", "/docs", "/openapi.json", "/api/watch/state"):
        assert client.get(path).status_code == 404, path


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
