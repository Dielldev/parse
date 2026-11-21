"""Deterministic verdict rules (build prompt Phase 5, step 6). The LLM never decides truth.

Evidence items arrive already labelled with a stance (by the NLI model or the LLM) and carry the source tier,
the origin group, and whether the claim lies inside the source's Tier-0 scope.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from atlas.settings import thresholds

VERDICTS = ("CONFIRMED", "CORROBORATED", "DISPUTED", "DEBUNKED", "UNVERIFIED")


@dataclass
class EvidenceItem:
    evidence_id: str
    stance: str  # supports | contradicts | unrelated
    tier: int
    origin_group: str
    in_tier0_scope: bool = False  # only meaningful when tier == 0


@dataclass
class Verdict:
    verdict: str
    evidence_ids: list[str]
    reason: str
    suggested_checks: list[str] = field(default_factory=list)


def effective_tier(e: EvidenceItem) -> int:
    """A Tier-0 source speaking outside its own scope is a party's claim, treated as Tier 3."""
    if e.tier == 0 and not e.in_tier0_scope:
        return 3
    return e.tier


def decide(items: list[EvidenceItem], media_recycled_from_unrelated_event: bool = False,
           cfg: dict | None = None) -> Verdict:
    v = (cfg or thresholds())["verifier"]
    rel = [e for e in items if e.stance in ("supports", "contradicts")]
    sup = [e for e in rel if e.stance == "supports"]
    con = [e for e in rel if e.stance == "contradicts"]
    t0_sup = [e for e in sup if effective_tier(e) == 0]
    t0_con = [e for e in con if effective_tier(e) == 0]
    ids = lambda xs: [e.evidence_id for e in xs]

    if media_recycled_from_unrelated_event or t0_con:
        why = []
        if t0_con:
            why.append(f"{len(t0_con)} Tier-0 source(s) contradict within their own scope")
        if media_recycled_from_unrelated_event:
            why.append("media matches an earlier, unrelated event")
        return Verdict("DEBUNKED", ids(t0_con), "; ".join(why) + ".",
                       ["Archive the original media and the earlier matching post.",
                        "Check whether the contradicting statement has since been updated."])
    if t0_sup and not con:
        return Verdict("CONFIRMED", ids(t0_sup), f"{len(t0_sup)} Tier-0 source(s) support within their own scope; "
                       "nothing contradicts.", ["Keep watching for a correction or retraction."])
    if sup and con:
        return Verdict("DISPUTED", ids(sup + con), f"{len(sup)} supporting and {len(con)} contradicting item(s).",
                       ["Seek a statement from the institution responsible for the claimed action.",
                        "Compare timestamps: which side is reacting to which?"])
    groups = {e.origin_group for e in sup if effective_tier(e) <= v["corroboration_max_tier"]}
    if len(groups) >= v["corroboration_min_origins"]:
        good = [e for e in sup if effective_tier(e) <= v["corroboration_max_tier"]]
        return Verdict("CORROBORATED", ids(good), f"{len(groups)} independent origin groups at tier <= "
                       f"{v['corroboration_max_tier']} support it.",
                       ["Look for a Tier-0 statement to confirm."])
    checks = []
    if not sup:
        checks.append("No supporting evidence yet: search Tier 0-1 sources for the same place and time.")
    elif len(groups) < v["corroboration_min_origins"]:
        checks.append(f"Only {len(groups)} independent origin group(s) at tier <= {v['corroboration_max_tier']}; "
                      f"need {v['corroboration_min_origins']}.")
    checks.append("Ask the responsible institution (police, KSF, KFOR) for a statement.")
    return Verdict("UNVERIFIED", ids(sup), "Not enough independent evidence either way.", checks)
