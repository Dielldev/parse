from datetime import datetime, timedelta, timezone

import pytest

from parse.scoring import significance as sig
from parse.scoring import tps
from parse.scoring.verdict import EvidenceItem as E, decide


# ---------------------------------------------------------------- TPS
def test_tps_formula_matches_brief():
    f = dict(severity=0.7, velocity=0.9, reach=0.6, coordination=0.8, offline_intent=0.4, proximity=1.0)
    r = tps.score(f, cred=0.85)
    expected = 100 * 0.85 * (0.25 * 0.7 + 0.20 * 0.9 + 0.15 * 0.6 + 0.15 * 0.8 + 0.15 * 0.4 + 0.10 * 1.0)
    assert r.tps == pytest.approx(expected, abs=0.05)
    assert r.priority == "P2"  # 61.6


@pytest.mark.parametrize("value,band", [(75, "P1"), (74.9, "P2"), (50, "P2"), (49.9, "P3"), (30, "P3"), (29.9, "P4")])
def test_bands(value, band):
    assert tps.band(value, []) == band


def test_tripwire_forces_p1_regardless_of_score():
    trips = tps.tripwires(labels={"T3"}, narratives=set(), has_explosive_term=True, names_critical_site=True,
                          has_weapons_term=False, names_kosovo_place=False, has_time_reference=False,
                          forged_official_order=False, doxxing_security_staff=False, t8_named_target=False,
                          serbian_mod_readiness=False)
    r = tps.score({"severity": 1.0}, cred=0.6, tripwires=trips)
    assert r.tps < 30 and r.priority == "P1"
    assert "Tripwire" in r.explanation


def test_tripwires_need_all_conditions():
    base = dict(labels={"T2"}, narratives=set(), has_explosive_term=False, names_critical_site=False,
                has_weapons_term=True, names_kosovo_place=True, has_time_reference=False,
                forged_official_order=False, doxxing_security_staff=False, t8_named_target=False,
                serbian_mod_readiness=False)
    assert tps.tripwires(**base) == []
    assert len(tps.tripwires(**{**base, "has_time_reference": True})) == 1


def test_severity_takes_highest_label():
    assert tps.severity(["T9", "T6", "T4"]) == 0.7
    assert tps.severity([]) == 0.0


def test_reach_log_scale_capped():
    assert tps.reach(10_000_000) == 1.0
    assert tps.reach(1000) == pytest.approx(3 / 7)
    assert tps.reach(None) == 0.0


def test_credibility_never_below_floor_and_only_lowers():
    assert tps.credibility(3, "DISPUTED") >= 0.6
    assert tps.credibility(0) == 1.0


def test_explanation_names_drivers():
    r = tps.score({"severity": 1.0, "velocity": 1.0}, cred=1.0)
    assert "how serious the labels are" in r.explanation and "spreading" in r.explanation


# ---------------------------------------------------------------- significance
def test_velocity_poisson_for_low_counts():
    f = sig.velocity_z(8, [1, 0, 2, 1, 1, 0, 1, 2])
    assert "Poisson" in f.note and f.value > 3 and 0 < f.normalised <= 1


def test_velocity_no_spike_is_zero():
    assert sig.velocity_z(1, [1, 1, 2, 1]).normalised == 0.0


def test_velocity_normal_z_for_high_counts():
    f = sig.velocity_z(60, [30, 32, 28, 31, 29, 30])
    assert "z-score" in f.note and f.value > 3


def test_independent_origins_counts_groups_once():
    assert sig.independent_origins(["g1", "g1", "g1"]).value == 1
    assert sig.independent_origins(["g1", "g2", "g3"]).value == 3


def test_cross_platform_gap():
    t0 = datetime(2026, 6, 28, 10, tzinfo=timezone.utc)
    f = sig.cross_platform({"telegram": t0, "news": t0 + timedelta(minutes=42)})
    assert f.value == 2 and "42 min" in f.note


def test_coordination_synchronised_frame_floor():
    f = sig.coordination(near_dup_share=0.0, new_account_share=0.0, max_fanout=0, synchronised_frame=True)
    assert f.normalised == 0.5


def test_proximity_north_and_calendar():
    quiet_day = datetime(2025, 4, 10, tzinfo=timezone.utc)
    assert sig.proximity(["Incident in Zvečan"], quiet_day).normalised == 1.0
    assert sig.proximity(["Incident in Prizren"], quiet_day).normalised == 0.5
    assert sig.proximity(["Statement on dialogue"], quiet_day).normalised == 0.0
    vidovdan = datetime(2026, 6, 27, 12, tzinfo=timezone.utc)
    assert "Vidovdan" in sig.proximity(["Statement on dialogue"], vidovdan).note


# ---------------------------------------------------------------- verdicts
def test_confirmed_needs_tier0_in_scope():
    assert decide([E("e1", "supports", 0, "g1", in_tier0_scope=True)]).verdict == "CONFIRMED"
    # A government speaking about the other side is a party's claim, not confirmation.
    assert decide([E("e1", "supports", 0, "g1", in_tier0_scope=False)]).verdict == "UNVERIFIED"


def test_corroborated_needs_two_independent_origin_groups():
    two_outlets_one_origin = [E("e1", "supports", 1, "tg_post_1"), E("e2", "supports", 1, "tg_post_1")]
    assert decide(two_outlets_one_origin).verdict == "UNVERIFIED"
    assert decide([E("e1", "supports", 1, "g1"), E("e2", "supports", 2, "g2")]).verdict == "CORROBORATED"
    assert decide([E("e1", "supports", 3, "g1"), E("e2", "supports", 3, "g2")]).verdict == "UNVERIFIED"


def test_disputed_when_both_sides_exist():
    v = decide([E("e1", "supports", 1, "g1"), E("e2", "supports", 1, "g2"), E("e3", "contradicts", 1, "g3")])
    assert v.verdict == "DISPUTED" and set(v.evidence_ids) == {"e1", "e2", "e3"}


def test_debunked_by_tier0_or_recycled_media():
    assert decide([E("e1", "supports", 1, "g1"), E("e2", "contradicts", 0, "g2", True)]).verdict == "DEBUNKED"
    assert decide([], media_recycled_from_unrelated_event=True).verdict == "DEBUNKED"


def test_unverified_lists_suggested_checks():
    v = decide([E("e1", "unrelated", 1, "g1")])
    assert v.verdict == "UNVERIFIED" and v.suggested_checks
