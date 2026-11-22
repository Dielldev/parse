"""Field agents: registry rules, Discord setup, and the Agents page."""
import pytest
from fastapi.testclient import TestClient

from parse.agents import registry_edit, runner
from parse.agents.methods import DISCORD_CHANNEL_RE, method_for, topic_match
from parse.models import Source
from parse.registry import import_sources


@pytest.fixture
def client(db, tmp_path, monkeypatch):
    import_sources(db)
    db.commit()
    csv_copy = tmp_path / "sources.csv"
    csv_copy.write_text(registry_edit.CSV_PATH.read_text())
    monkeypatch.setattr(registry_edit, "CSV_PATH", csv_copy)   # never touch the real registry file
    from parse.web.app import app
    return TestClient(app)


def test_topic_match_folds_scripts_and_diacritics():
    assert topic_match(["zvecan"], "Napad u Zvečanu")
    assert topic_match(["zvecan"], "Напад у Звечану")
    assert not topic_match(["banjska"], "Nothing relevant")
    assert topic_match([], "anything")


def test_method_choice():
    assert method_for(Source(source_id="a", platform="discord", url="x", name="a", tier=2, status="v", mvp_collect="yes")) == "discord"
    assert method_for(Source(source_id="b", platform="news", name="b", tier=1, status="v", mvp_collect="yes",
                             check_note="wp_api=True", feed_urls=["f"])) == "wp-search"
    assert method_for(Source(source_id="c", platform="news", name="c", tier=1, status="v", mvp_collect="yes",
                             feed_urls=["f"])) == "rss"
    assert method_for(Source(source_id="d", platform="news", name="d", tier=1, status="v", mvp_collect="yes")) == "none"


def test_agents_page_renders(client):
    r = client.get("/agents")
    assert r.status_code == 200 and "Send a scout." in r.text and "How the scout reads" in r.text
    for name in ("Telegram", "Discord", "Reddit", "News sites"):
        assert name in r.text


def test_discord_channel_added_to_registry_and_csv(client, db):
    assert not DISCORD_CHANNEL_RE.match("https://discord.gg/invite123")
    bad = client.post("/api/agents/discord/channels", json={"url": "https://discord.gg/abc", "name": "x"})
    assert bad.status_code == 400
    r = client.post("/api/agents/discord/channels",
                    json={"url": "https://discord.com/channels/111/222", "name": "Test #kosovo", "tier": 3})
    assert r.status_code == 200 and r.json()["id"] == "src_dc_222"
    db.expire_all()
    src = db.get(Source, "src_dc_222")
    assert src.platform == "discord" and src.tier == 3 and runner.ready(src)
    assert "src_dc_222" in registry_edit.CSV_PATH.read_text()


def test_discord_without_token_reports_setup(client, db, monkeypatch):
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    client.post("/api/agents/discord/channels", json={"url": "https://discord.com/channels/111/333", "name": "t"})
    run_id = client.post("/api/agents/dispatch", json={"kind": "discord", "sources": ["src_dc_333"]}).json()["run_id"]
    run = runner.wait(run_id, 10)
    assert run["stats"]["src_dc_333"]["state"] == "setup"
    assert "DISCORD_BOT_TOKEN" in run["stats"]["src_dc_333"]["note"]


def test_blocked_sources_cannot_be_approved(client, db):
    blocked = next(x for x in db.query(Source).all() if x.mvp_collect.startswith("blocked"))
    assert client.post(f"/api/agents/approve/{blocked.source_id}").status_code == 400


def test_parked_telegram_source_is_gated_until_approved(client, db):
    tg = next(x for x in db.query(Source).filter(Source.platform == "telegram").all() if not runner.ready(x))
    run_id = runner.start("telegram", "", [tg.source_id])
    assert runner.wait(run_id, 10)["stats"][tg.source_id]["state"] == "blocked"   # registry gate, no request sent
    assert client.post(f"/api/agents/approve/{tg.source_id}").status_code == 200
    db.expire_all()
    assert runner.ready(db.get(Source, tg.source_id))


# ---------------------------------------------------------------- browser scout (no browser is launched here)
def test_scout_parses_what_people_type():
    from parse.agents import scout
    assert scout.parse_target("telegram", "https://t.me/balkanar")["url"] == "https://t.me/s/balkanar"
    assert scout.parse_target("telegram", "@balkanar")["id"] == "src_tg_balkanar"
    assert scout.parse_target("reddit", "r/kosovo")["url"] == "https://www.reddit.com/r/kosovo/"
    assert scout.parse_target("reddit", "https://old.reddit.com/r/serbia/new")["handle"] == "serbia"
    assert scout.parse_target("x", "https://x.com/NATO_KFOR")["label"] == "@NATO_KFOR"
    assert scout.parse_target("discord", "https://discord.com/channels/11/22")["id"] == "src_dc_22"
    assert scout.parse_target("x", "") is None
    with pytest.raises(ValueError):
        scout.parse_target("discord", "https://discord.gg/invite")


def test_scout_plan_needs_a_target_or_topic(client):
    from parse.agents import scout
    with pytest.raises(ValueError):
        scout.plan("discord", "", "kurti")
    with pytest.raises(ValueError):
        scout.plan("x", "", "")
    assert scout.plan("reddit", "", "banjska")[0]["id"] == "src_rd_search"
    assert all(t["url"].startswith("https://t.me/s/") for t in scout.plan("telegram", "", ""))


def test_scout_registers_new_targets_and_respects_blocks(client, db):
    from parse.agents import scout
    src = scout.ensure_source(db, "telegram", scout.parse_target("telegram", "@parse_test_channel"))   # flushed; rolled back after
    assert src.origin == "browser-scout" and src.tier == 3
    assert "src_tg_parse_test_channel" in registry_edit.CSV_PATH.read_text()
    blocked = next(x for x in db.query(Source).all() if x.mvp_collect.startswith("blocked"))
    with pytest.raises(scout.Refused):
        scout.ensure_source(db, blocked.platform, {"id": blocked.source_id, "url": blocked.url or "x", "label": "b"})


def test_scout_tags_framing():
    from parse.agents import scout
    assert "War / persecution" in scout.tags_of("Kurti sprema rat, teror nad Srbima")
    assert "North" in scout.tags_of("Напад у Звечану")
    assert scout.tags_of("weather is nice") == []


def test_scout_api_rejects_bad_input(client):
    assert client.post("/api/scout/start", json={"platform": "discord", "target": "nope"}).status_code == 400
    assert client.post("/api/scout/start", json={"platform": "myspace", "target": "x"}).status_code == 400
    assert client.get("/api/scout/runs/run_missing").status_code == 404
    assert client.get("/api/scout/status").json()["busy"] in (None, "scout", "window")
