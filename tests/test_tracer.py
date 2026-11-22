"""Tracer (A12, brief Section 10): edges, origin groups, origin choice, amplifiers, discovery, attribution guard."""
from datetime import datetime, timedelta, timezone

import pytest

from atlas import tracer as T

C = {"copy_jaccard": 0.25, "quote_containment": 0.45, "quote_min_shared": 6, "translate_cosine": 0.76,
     "max_edge_gap_days": 14, "ambiguous_origin_minutes": 30, "common_media_share": 0.2}
T0 = datetime(2024, 11, 29, 19, 5, 41, tzinfo=timezone.utc)
STORY = ("Snažna eksplozija kod Zubinog Potoka oštetila je kanal Ibar-Lepenac, voda curi a snabdevanje je "
         "prekinuto za veći deo opštine prema prvim informacijama sa terena")


def node(i, minutes, text=STORY, src="s1", lang="sr-Latn", tier=1, platform="news", links=(), media=(), vec=None,
         when=None, url=None):
    return T.Node(id=i, source_id=src, source=src.upper(), tier=tier, platform=platform, lang=lang,
                  published_at=when if when is not None else (T0 + timedelta(minutes=minutes)), first_seen_at=None,
                  url=url or f"https://{src}.example/{i}", title=text[:40], body=text, links=list(links),
                  media=list(media), vec=vec)


def test_copy_edge_points_from_earlier_to_later():
    a, b = node("a", 0, src="kossev"), node("b", 30, src="nova")
    e = T.pair_edge(a, b, C)
    assert e["type"] == "copy" and e["from"] == "a" and e["to"] == "b"


def test_link_beats_copy_and_unrelated_text_has_no_edge():
    a = node("a", 0, src="kossev")
    b = node("b", 30, src="nova", links=[a.url + "/"])
    assert T.pair_edge(a, b, C)["type"] == "link"
    c = node("c", 40, text="Skupština opštine danas raspravlja o budžetu za sledeću godinu i školama", src="x")
    assert T.pair_edge(a, c, C) is None


def test_translate_edge_needs_other_language_and_close_meaning():
    a = node("a", 0, lang="sq", text="Shpërthim në Zubin Potok", vec=[1.0, 0.0])
    b = node("b", 20, lang="sr-Cyrl", text="Експлозија у Зубином Потоку", vec=[0.8, 0.6])
    assert T.pair_edge(a, b, C)["type"] == "translate"
    b2 = node("b2", 20, lang="sr-Latn", text="Eksplozija u Zubinom Potoku", vec=[0.8, 0.6])
    c2 = node("c2", 25, lang="sr-Cyrl", text="Нешто сасвим друго", vec=[0.8, 0.6])
    assert T.pair_edge(b2, c2, C) is None   # Latin and Cyrillic Serbian are one language, not a translation


def test_same_image_from_another_source_is_a_copy_but_site_defaults_are_not():
    img = "https://cdn.example/uploads/2024/11/eksplozija-kanal-ibar-1024x576.jpg"
    a = node("a", 0, text="prvi tekst o nečemu", src="a", media=[img])
    b = node("b", 10, text="drugi potpuno drugačiji sadržaj", src="b", media=[img.replace("-1024x576", "")])
    assert T.pair_edge(a, b, C)["via"] == "same image"
    assert T.pair_edge(a, b, C, common_media=frozenset({T.media_key(img)})) is None


def test_graph_origin_groups_and_origin():
    a = node("a", 0, src="kossev")
    b = node("b", 20, src="nova")
    c = node("c", 50, src="kurir", links=[b.url])
    d = node("d", 5, text="Ambasadori EU i SAD osuđuju napad i traže hitnu istragu o odgovornima za štetu", src="n1")
    parent = T.build_graph([a, b, c, d], C)
    assert parent["c"]["type"] == "link" and parent["c"]["from"] == "b"
    group = T.groups_of([a, b, c, d], parent)
    assert group["b"] == group["c"] == "a" and group["d"] == "d"
    o = T.pick_origin([a, b, c, d], parent, group, C)
    assert o["signal_id"] == "a" and 0 < o["confidence"] < 0.9
    assert any("5 min later" in r for r in o["reasons"])   # d is an independent post 5 minutes after a


def test_date_only_post_does_not_beat_a_same_day_post_with_a_time():
    midnight = T0.replace(hour=0, minute=0, second=0)
    early = node("early", 0, src="kossev")
    dated = node("dated", 0, src="kosovo-online", when=midnight)
    assert dated.date_only and dated.when > early.when
    parent = T.build_graph([early, dated], C)
    o = T.pick_origin([early, dated], parent, T.groups_of([early, dated], parent), C)
    assert o["signal_id"] == "early"


def test_pasted_text_is_never_a_parent():
    probe = node("probe", 0)
    probe.probe, probe.published_at = True, None   # pasted text has no publish time
    a = node("a", 10, src="kossev")
    parent = T.build_graph([probe, a], C)
    assert "a" not in parent and parent["probe"]["from"] == "a"


def test_amplifier_reach_counts_other_sources_only():
    a = node("a", 0, src="kossev")
    b = node("b", 10, src="kossev", links=[a.url])     # same outlet's follow-up
    c = node("c", 20, src="nova", links=[b.url])
    d = node("d", 30, src="kurir", links=[c.url])
    parent = T.build_graph([a, b, c, d], C)
    amps = {x["source_id"]: x for x in T.amplifiers([a, b, c, d], parent, "a")}
    assert amps["kossev"]["reach"] == 2    # b -> c, d (both other outlets); b's own outlet does not count
    assert amps["nova"]["reach"] == 1


@pytest.mark.parametrize("url,want", [
    ("https://t.me/s/some_channel/1234", "https://t.me/s/some_channel"),
    ("https://x.com/SomeHandle/status/1?ref=x", "https://x.com/SomeHandle"),
    ("https://www.facebook.com/sharer/sharer.php?u=x", None),
    ("https://en.wikipedia.org/wiki/Kosovo", None),
    ("https://unknown-portal.rs/vesti/123", "https://unknown-portal.rs/"),
])
def test_upstream_of(url, want):
    assert T.upstream_of(url) == want


def test_attribution_guard():
    assert T.attribution_ok("The earliest observed source is KoSSev; it was amplified by Sputnik Srbija.")
    assert not T.attribution_ok("Serbia orchestrated the campaign through Sputnik.")
    assert not T.attribution_ok("The Kremlin is behind these posts.")


def test_seed_terms_prefer_title_stems_and_skip_outlet_name():
    terms = T.seed_terms("KoSSev prati. Pratite nas na Telegramu. Voda curi iz kanala.",
                         "Detonacija u Donjim Varagama, curi voda iz kanala Ibar-Lepenac", avoid="KoSSev kossev.info")
    assert "lepen" in terms and "varag" in terms and "kossev" not in terms and "telegram" not in terms


def test_diverse_cut_keeps_other_languages():
    seed = node("s", 0)
    sr = [node(f"sr{i}", i) for i in range(10)]
    sq = [node(f"sq{i}", i, lang="sq") for i in range(3)]
    kept = T.diverse_cut(sr + sq + [seed], 6, seed, key=lambda n: n.id)
    assert kept[0] is seed and sum(n.lang == "sq" for n in kept) >= 2


@pytest.mark.parametrize("raw,want", [(5400, 5400), ("5400", 5400), ("6.48K", 6480), ("1.2M", 1200000), ("", 0), ("n/a", 0)])
def test_engagement_counts(raw, want):
    assert T.count(raw) == want


def test_earlier_post_nothing_copies_is_context_not_origin():
    ctx = node("ctx", -35, text="Policija pojačala mere na severu, više patrola i punktova u kritičnim zonama", src="kossev")
    a, b = node("a", 0, src="kossev"), node("b", 20, src="nova")
    parent = T.build_graph([ctx, a, b], C)
    group = T.groups_of([ctx, a, b], parent)
    assert T.pick_origin([ctx, a, b], parent, group, C, seed_id="b")["signal_id"] == "a"


def test_sidebar_links_from_one_outlet_are_not_evidence():
    side = node("side", -30, text="Policija pojačala mere na severu, više patrola i punktova u kritičnim zonama",
                src="kossev")
    posts = [node(f"p{i}", 10 * i, text=f"{STORY} {i}" if i == 0 else f"Sasvim druga vest broj {i} o drugoj temi danas",
                  src="kossev", links=[side.url]) for i in range(4)]
    parent = T.build_graph([side] + posts, C)
    assert not any(e["from"] == "side" for e in parent.values())
