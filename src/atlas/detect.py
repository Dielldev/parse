"""Threat detection with featherless-ai/Qwen3.5-4B-classifier via POST /v1/classifier.

One call per post asks one yes/no ("noul") question per threat label, narrative and offline intent; the
endpoint returns a probability for each (0.01..0.99), billed on input tokens only. These raw probabilities
are calibrated later with temperature scaling fitted on the validation split (Phase 3), never trusted raw.
The rights rule is part of every question's instructions.
"""
from __future__ import annotations

from atlas.label_teacher import MAX_TEXT_CHARS

ROLE = "detector"
PROMPT_VERSION = "detect-v1"

RIGHTS = (" Lawful protest, journalism, opposition politics and criticism of a government are never enough on "
          "their own; reporting on an incident is not the incident. Ignore the author's language or ethnicity.")

T_DEFS = {
    "T1": "Serbian military pressure aimed at Kosovo: movements, exercises, readiness changes, mobilisation language.",
    "T2": "Armed groups or paramilitaries: recruitment or volunteer calls, glorifying Banjska, weapons caches, funding attackers.",
    "T3": "Sabotage or attacks on water, energy, transport or communications infrastructure (canal, Gazivoda, KEK, substations).",
    "T4": "Police-community flashpoints: calls to gather at stations/bridges/crossings, false arrest captions, doxxing officers, fake police statements.",
    "T5": "Protest escalation: protest turning violent, roadblocks, barricades, 'protest' becoming 'defend', mobilisation logistics.",
    "T6": "Information operation: pushes a hostile narrative (N1-N11) against institutions, KSF, NATO or social cohesion, or deepfakes.",
    "T7": "Cyber or digital exposure: DDoS, intrusions, leaks, phishing, hacktivist target lists, KSF OPSEC lapses.",
    "T8": "Violent extremism: jihadist or ethnonationalist calls to violence, named targets (churches, monasteries, mosques, KFOR).",
    "T9": "Political instability adversaries can exploit: deadlock, crisis, snap-election triggers, friction with allies, UNSCR 1244 disputes (not routine politics).",
    "T10": "Crime-security nexus: weapons for sale, smuggling, illegal crossings, payment links funding hostile activity.",
}
N_DEFS = {
    "N1": "KSF is the KLA reborn / an illegal army under UNSCR 1244.",
    "N2": "Pogrom, ethnic cleansing or 'terror against Serbs' by Kurti's regime.",
    "N3": "NATO / KFOR is abandoning Kosovo.",
    "N4": "The West is betraying Albanians / the EU punishes Kosovo.",
    "N5": "Kosovo is a terrorist, drug or mafia state.",
    "N6": "Fake orders, mobilisation notices or statements attributed to officials (deepfakes).",
    "N7": "Serbia will return / imminent intervention / volunteers.",
    "N8": "Election fraud / institutions are illegitimate.",
    "N9": "Priština or Kurti is preparing for war: arming, Turkish weapons, ammunition factory, gendarmerie.",
    "N10": "Kurti erases Serbian heritage: churches, monasteries, rewriting the Battle of Kosovo.",
    "N11": "Kurti alone blocks dialogue / Priština is the only obstacle to peace.",
}


def questions() -> dict:
    q = {}
    for code, d in T_DEFS.items():
        q[code] = {"type": "noul", "instructions": f"Does this post carry threat {code}? {d}{RIGHTS}",
                   "criteria": {"true": "Indicators of this threat are present in the post",
                                "false": "Not present, or only reported neutrally"}}
    for code, d in N_DEFS.items():
        q[code] = {"type": "noul", "instructions": f"Does the post itself push or repeat this narrative "
                                                   f"(not merely report or debunk it)? {d}",
                   "criteria": {"true": "Pushes the narrative", "false": "Does not"}}
    q["offline_intent"] = {"type": "noul", "instructions": "Does the post call for, organise or announce physical "
                           "action (gather, block, barricade, attack) or give a time and place for it?" + RIGHTS,
                           "criteria": {"true": "Calls for physical action", "false": "No call to action"}}
    return q


def post_text(title: str | None, text: str | None) -> str:
    return f"Title: {title or ''}\n\n{(text or '')[:MAX_TEXT_CHARS]}"


def parse(answers: dict) -> dict[str, float]:
    return {k: float(v["noul"]) for k, v in answers.items() if v.get("type") == "noul"}


def detect(fl, title: str | None, text: str | None, stage: str = "detect") -> tuple[dict[str, float], dict]:
    answers, usage = fl.classify(ROLE, stage, post_text(title, text), questions())
    return parse(answers), usage


NLI_QUESTION = {"stance": {
    "type": "choice",
    "instructions": "Judge ONLY from the evidence text whether it supports or contradicts the claim. "
                    "Do not use outside knowledge.",
    "criteria": {"supports": "The evidence states or clearly implies the claim is true",
                 "contradicts": "The evidence states or clearly implies the claim is false",
                 "unrelated": "The evidence does not address the claim"}}}


def stance(fl, claim: str, evidence: str) -> tuple[str, dict[str, float], dict]:
    """NLI-style stance for the Verifier. Returns the chosen label and its probability per option."""
    answers, usage = fl.classify("nli", "verify-stance", f"CLAIM:\n{claim}\n\nEVIDENCE:\n{evidence[:4000]}",
                                 NLI_QUESTION)
    a = answers["stance"]
    return a["choice"], a["probabilities"], usage
