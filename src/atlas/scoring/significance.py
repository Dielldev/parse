"""Significance features per Event (build prompt Phase 4). Each returns a value plus a plain-language note."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from atlas.settings import keywords, thresholds
from atlas.normalise.text import fold


@dataclass
class Feature:
    value: float
    normalised: float  # 0..1, what the TPS formula consumes
    note: str


def _poisson_sf(k: int, lam: float) -> float:
    """P(X >= k) for X ~ Poisson(lam)."""
    if k <= 0:
        return 1.0
    term, cdf = math.exp(-lam), 0.0
    for i in range(k):
        cdf += term
        term *= lam / (i + 1)
    return max(0.0, 1.0 - cdf)


def _sf_to_z(p: float) -> float:
    """Upper-tail probability -> standard-normal z (Acklam-free bisection; plenty accurate here)."""
    p = min(max(p, 1e-12), 1 - 1e-12)
    lo, hi = -10.0, 10.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if 0.5 * math.erfc(mid / math.sqrt(2)) > p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def velocity_z(count_last_hour: int, baseline_counts: list[int], cfg: dict | None = None) -> Feature:
    """Posts in the last 60 min vs. the same narrative cluster's counts at the same hour-of-week.

    Low baseline (mean < poisson_low_count): one-sided Poisson tail converted to z.
    Otherwise: classic z with the sample standard deviation (floored at sqrt(mean))."""
    c = (cfg or thresholds())["significance"]
    n = len(baseline_counts)
    mean = sum(baseline_counts) / n if n else 0.0
    if mean < c["poisson_low_count"]:
        lam = max(mean, 0.5)  # floor so an empty baseline doesn't make 1 post infinitely surprising
        z = _sf_to_z(_poisson_sf(count_last_hour, lam)) if count_last_hour > lam else 0.0
        method = f"Poisson (baseline mean {mean:.1f}/h over {n} comparable hours)"
    else:
        var = sum((x - mean) ** 2 for x in baseline_counts) / max(n - 1, 1)
        sd = max(math.sqrt(var), math.sqrt(mean))
        z = (count_last_hour - mean) / sd
        method = f"z-score (baseline {mean:.1f}±{sd:.1f}/h over {n} comparable hours)"
    norm = max(0.0, min(1.0, z / c["velocity_z_cap"]))
    ratio = f"x{count_last_hour / mean:.1f}" if mean > 0 else "no baseline activity"
    return Feature(z, norm, f"{count_last_hour} posts in the last hour, {ratio} baseline; z={z:.1f} by {method}.")


def independent_origins(origin_groups: list[str]) -> Feature:
    k = len(set(origin_groups))
    return Feature(k, min(1.0, (k - 1) / 4) if k else 0.0,
                   f"{k} independent origin group(s); reposts of the same original count once.")


def cross_platform(first_seen_by_platform: dict[str, datetime]) -> Feature:
    plats = sorted(first_seen_by_platform, key=first_seen_by_platform.get)
    if len(plats) < 2:
        return Feature(len(plats), 0.0, f"Seen on {len(plats)} platform(s) only.")
    gap = first_seen_by_platform[plats[1]] - first_seen_by_platform[plats[0]]
    mins = gap.total_seconds() / 60
    return Feature(len(plats), min(1.0, (len(plats) - 1) / 3),
                   f"On {len(plats)} platforms ({', '.join(plats)}); jumped from {plats[0]} to {plats[1]} "
                   f"after {mins:.0f} min.")


def coordination(*, near_dup_share: float, new_account_share: float, max_fanout: int,
                 synchronised_frame: bool = False, cfg: dict | None = None) -> Feature:
    c = (cfg or thresholds())["significance"]
    w = c["coordination_weights"]
    fan = min(1.0, max_fanout / c["fanout_saturation"])
    v = w["near_dup_share"] * near_dup_share + w["new_account_share"] * new_account_share + w["fanout"] * fan
    note = (f"{near_dup_share:.0%} near-duplicates within {c['near_duplicate_window_minutes']} min, "
            f"{new_account_share:.0%} accounts under {c['new_account_days']} days old, fan-out {max_fanout}.")
    if synchronised_frame:
        v = max(v, 0.5)
        note += (f" Same frame in >= {c['synchronised_frame_outlets']} outlets within "
                 f"{c['synchronised_frame_hours']} h (brief 5.4c).")
    return Feature(v, min(1.0, v), note)


def in_trigger_window(when: datetime) -> str | None:
    kw = keywords()
    before = timedelta(hours=kw["trigger_window_hours_before"])
    after = timedelta(hours=kw["trigger_window_hours_after"])
    for ev in kw["trigger_calendar"]:
        for year in (when.year - 1, when.year, when.year + 1):
            try:
                d = datetime(year, ev["month"], ev["day"], tzinfo=when.tzinfo)
            except ValueError:
                continue
            if d - before <= when <= d + after:
                return ev["name"]
    return None


def proximity(texts: list[str], when: datetime) -> Feature:
    kw = keywords()
    blob = fold(" ".join(texts))
    hits = [p for group in kw["proximity_sensitive"].values() for p in group if fold(p) in blob]
    trig = in_trigger_window(when)
    if hits or trig:
        why = []
        if hits:
            why.append("names " + ", ".join(sorted(set(hits))[:5]))
        if trig:
            why.append(f"falls in the trigger window for {trig}")
        return Feature(1.0, 1.0, "Sensitive: " + "; ".join(why) + ".")
    other = [p for p in kw["proximity_kosovo_other"] if fold(p) in blob]
    if other:
        return Feature(0.5, 0.5, "Names other places in Kosovo: " + ", ".join(sorted(set(other))[:5]) + ".")
    return Feature(0.0, 0.0, "No sensitive place or date.")
