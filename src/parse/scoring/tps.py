"""Threat Priority Score (brief Section 8). Pure functions; weights come from config/thresholds.yaml."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from parse.settings import thresholds

FACTORS = ("severity", "velocity", "reach", "coordination", "offline_intent", "proximity")
PLAIN = {
    "severity": "how serious the labels are",
    "velocity": "how fast it is spreading against its baseline",
    "reach": "audience size of the posting accounts",
    "coordination": "signs of coordinated amplification",
    "offline_intent": "calls to gather, block or attack",
    "proximity": "closeness to sensitive places or dates",
}


@dataclass
class TPSResult:
    tps: float
    priority: str
    factors: dict
    credibility: float
    tripwires: list[str] = field(default_factory=list)
    explanation: str = ""


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def severity(labels: list[str], cfg: dict | None = None) -> float:
    table = (cfg or thresholds())["tps"]["severity_by_label"]
    return max((table.get(l, 0.0) for l in labels), default=0.0)


def reach(total_followers: int | None, cfg: dict | None = None) -> float:
    div = (cfg or thresholds())["tps"]["reach_log10_divisor"]
    if not total_followers or total_followers <= 1:
        return 0.0
    return clamp01(math.log10(total_followers) / div)


def credibility(best_tier: int | None, verdict: str | None = None, cfg: dict | None = None) -> float:
    """Never removes an alert; only lowers the score, and never below credibility_min."""
    t = (cfg or thresholds())["tps"]
    c = t["credibility_by_tier"].get(best_tier if best_tier is not None else 3, t["credibility_by_tier"][3])
    if verdict:
        c *= t["credibility_by_verdict"].get(verdict, 1.0)
    return max(t["credibility_min"], min(1.0, c))


def band(tps: float, tripwires: list[str], cfg: dict | None = None) -> str:
    b = (cfg or thresholds())["tps"]["bands"]
    if tripwires or tps >= b["P1"]:
        return "P1"
    if tps >= b["P2"]:
        return "P2"
    if tps >= b["P3"]:
        return "P3"
    return "P4"


def score(factors: dict, cred: float, tripwires: list[str] | None = None, cfg: dict | None = None) -> TPSResult:
    cfg = cfg or thresholds()
    w = cfg["tps"]["weights"]
    f = {k: clamp01(factors.get(k, 0.0)) for k in FACTORS}
    weighted = {k: w[k] * f[k] for k in FACTORS}
    tps = round(100 * cred * sum(weighted.values()), 1)
    trips = list(tripwires or [])
    pr = band(tps, trips, cfg)
    return TPSResult(tps=tps, priority=pr, factors=f, credibility=cred, tripwires=trips,
                     explanation=explain(tps, pr, f, weighted, cred, trips))


def explain(tps, pr, f, weighted, cred, trips) -> str:
    total = sum(weighted.values()) or 1.0
    top = sorted(weighted.items(), key=lambda kv: kv[1], reverse=True)
    drivers = [f"{PLAIN[k]} ({f[k]:.2f}, {100 * v / total:.0f}% of score)" for k, v in top if v > 0][:3]
    parts = [f"TPS {tps:.0f} -> {pr}."]
    if trips:
        parts.append("Tripwire forced P1: " + "; ".join(trips) + ".")
    parts.append("Main drivers: " + (", ".join(drivers) if drivers else "none") + ".")
    if cred < 1.0:
        parts.append(f"Score lowered by credibility x{cred:.2f} (source tier / verification status).")
    return " ".join(parts)


# ---------------------------------------------------------------- tripwires (brief s8)
def tripwires(*, labels: set[str], narratives: set[str], has_explosive_term: bool, names_critical_site: bool,
              has_weapons_term: bool, names_kosovo_place: bool, has_time_reference: bool,
              forged_official_order: bool, doxxing_security_staff: bool, t8_named_target: bool,
              serbian_mod_readiness: bool) -> list[str]:
    out = []
    if "T3" in labels and has_explosive_term and names_critical_site:
        out.append("T3 + explosive/sabotage term + named critical-infrastructure site")
    if "T2" in labels and has_weapons_term and names_kosovo_place and has_time_reference:
        out.append("T2 + weapons + place in Kosovo + time reference")
    if "N6" in narratives and forged_official_order:
        out.append("N6 suspected forged order or deepfake of KSF/MoD/PM/President")
    if doxxing_security_staff:
        out.append("Doxxing of KSF or police personnel")
    if "T8" in labels and t8_named_target:
        out.append("T8 with a named target")
    if serbian_mod_readiness:
        out.append("Serbian MoD readiness or mobilisation statement")
    return out
