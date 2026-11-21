from datetime import date, datetime, timezone

import pytest

from atlas import budget
from atlas.collectors.backfill import Window, _even_sample, date_hint, slug_relevant, window_candidates
from atlas.collectors.emit import published_from_html
from atlas.normalise.text import detect_lang, fold, is_kosovo_relevant, sr_cyr_to_lat


def test_transliteration_and_fold():
    assert sr_cyr_to_lat("Косово и Метохија, Ђаковица, Џеп") == "Kosovo i Metohija, Đakovica, Džep"
    assert fold("Zveçan ZVEČAN Звечан") == "zvecan zvecan zvecan"


@pytest.mark.parametrize("text,lang", [
    ("Policia e Kosovës arrestoi dy persona në veri të Mitrovicës gjatë natës.", "sq"),
    ("Kosovska policija uhapsila je dvojicu u severnoj Mitrovici tokom noći.", "sr-Latn"),
    ("Косовска полиција ухапсила је двојицу у северној Митровици током ноћи.", "sr-Cyrl"),
    ("Косовская полиция задержала двоих в северной Митровице ночью.", "ru"),
    ("Kosovo Police detained two people in north Mitrovica overnight.", "en"),
])
def test_detect_lang(text, lang):
    assert detect_lang(text) == lang


def test_relevance_short_codes_need_word_boundary():
    assert is_kosovo_relevant("Pripadnici FSK učestvovali su u vežbi")
    assert not is_kosovo_relevant("The fskx library released a new version")
    assert not is_kosovo_relevant("Football results from the weekend")


def test_date_hint_day_and_month():
    assert date_hint("https://x.rs/2024/11/29/eksplozija") == (date(2024, 11, 29), date(2024, 11, 29))
    assert date_hint("https://x.rs/sitemap-2024-11.xml") == (date(2024, 11, 1), date(2024, 11, 30))
    assert date_hint("https://x.rs/vesti/eksplozija-123") is None


def test_window_candidates_filter_by_date_and_slug():
    w = Window("canal", datetime(2024, 11, 25, tzinfo=timezone.utc), datetime(2024, 12, 7, tzinfo=timezone.utc), "val")
    entries = [
        ("https://x.rs/2024/11/29/eksplozija-kanal-ibar", None),       # in window, relevant
        ("https://x.rs/2024/11/29/fudbal-rezultati", None),            # in window, not relevant
        ("https://x.rs/2023/01/02/kosovo-vesti", None),                # relevant, wrong date
        ("https://x.rs/vesti/kurti-sednica", datetime(2024, 11, 30, tzinfo=timezone.utc)),
        ("https://x.rs/vesti/kurti-bez-datuma", None),                 # undated: skipped
    ]
    assert window_candidates(entries, w) == ["https://x.rs/2024/11/29/eksplozija-kanal-ibar",
                                             "https://x.rs/vesti/kurti-sednica"]
    assert slug_relevant("https://x.rs/%D0%BA%D0%BE%D1%81%D0%BE%D0%B2%D0%BE-vesti")  # percent-encoded Cyrillic


def test_even_sample_spreads_over_time():
    assert _even_sample(list(range(100)), 4) == [0, 25, 50, 75]


def test_published_from_html_prefers_meta():
    html = b'<html><head><meta property="article:published_time" content="2026-06-28T09:41:00+02:00"></head></html>'
    assert published_from_html(html) == datetime(2026, 6, 28, 7, 41, tzinfo=timezone.utc)
