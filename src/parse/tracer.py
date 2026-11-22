"""A12 Tracer: from one post, a pasted text, a screenshot or a link back to the earliest observed source.

The brief's problem statement: when a threat-relevant story about Kosovo spreads, analysts find out late and cannot
see where it started or who is pushing it. The Tracer answers "where did this come from, and how did it travel?"
by following brief Section 10 step by step:

  1 seed        the signal, text, screenshot (read with OCR) or link to trace
  2 expand      search the archive backwards and forwards: shared words, outgoing links, the same image, close meaning
  3 graph       typed edges from the earlier post to the later one: forward, quote, copy, link, translate
  4 origin      earliest node with no inbound edge, with a confidence and every reason it was lowered
  5 amplifiers  sources ranked by downstream reach, and how often each amplified in earlier traces
  6 discover    upstream sites outside the registry go to the discovery queue for a human to approve
  7 real world  official (Tier 0) statements and trigger-calendar dates around the story

Then it scores the event (significance + Threat Priority Score), checks the claim against one item per independent
origin group (verdict by the fixed rules in scoring/verdict.py), and writes a brief in the Section 10 attribution
wording ("earliest observed source", "amplified by"; never "Serbia/Russia did X").

Steps 1-7 and the score are local and free. Only the stance checks and the written brief call a model, and only when
the answer engine is Qwen; without it the verdict says plainly that stance was not checked.
"""
from __future__ import annotations

import base64
import math
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterator
from urllib.parse import urlparse

from sqlalchemy import Integer, cast, func, or_, select

from parse.db import session
from parse.ids import new_id
from parse.models import DiscoveryQueue, Event, EventEdge, EventSignal, Signal, Source
from parse.normalise.text import fold
from parse.scoring import significance as sig_mod
from parse.scoring import tps as tps_mod
from parse.scoring.verdict import EvidenceItem, decide
from parse.settings import thresholds

TIER_NAMES = {0: "Official / primary", 1: "Established outlet", 2: "Specialist OSINT", 3: "Partisan or unverified"}
# Explicit evidence beats textual likeness: a forward or a link says where a post came from; a copy only suggests it.
EDGE_RANK = {"forward": 5, "link": 4, "quote": 3, "copy": 2, "translate": 1}
EDGE_HELP = {
    "forward": "re-posted as a forward of the earlier post",
    "link": "links to the earlier post",
    "quote": "quotes a long passage of the earlier post",
    "copy": "repeats the earlier post's wording (or its image)",
    "translate": "says the same thing in another language",
}
LANG_FAMILY = {"sr-Latn": "sr", "sr-Cyrl": "sr", "sr": "sr", "hr": "sr", "bs": "sr"}
PROBE_ID = "probe"
STOP_TERMS = set("""
also after before about would could should their there them they this that these those from with have been were
will which what when where while into over under than then more most such some only other said says according
kosovo kosova kosove kosoves kosovu srbije srbija serbia news vesti lajme today danas sot
kosovska kosovski kosovske kosovskoj kosovsko telegram facebook twitter instagram youtube video foto photo pratite
follow read more procitajte lexo kliko komentari komentar komente
""".split())

# Section 10 attribution rule, enforced on every brief: name the earliest observed source and who amplified it, never
# a state or leader as the author of an operation. A model brief that breaks this is thrown away.
_ACTORS = r"(serbia|serbian government|belgrade|russia|russian government|moscow|kremlin|albania|tirana|kurti|vucic|" \
          r"vučić|putin|kosovo government|pristina|prishtina)"
_ACTS = r"(did|orchestrated|launched|ordered|is behind|was behind|are behind|planted|staged|ran|runs|directed|" \
        r"coordinated|masterminded|fabricated|created|started)"
ATTRIBUTION_BAD = re.compile(rf"\b{_ACTORS}\b[^.;:]{{0,40}}\b{_ACTS}\b", re.I)


def attribution_ok(text: str) -> bool:
    return not ATTRIBUTION_BAD.search(text or "")


def cfg() -> dict:
    return thresholds()["tracer"]


# ---------------------------------------------------------------- nodes and similarity (pure, no database)
@dataclass
class Node:
    id: str
    source_id: str
    source: str
    tier: int
    platform: str
    lang: str | None
    published_at: datetime | None
    first_seen_at: datetime | None
    url: str
    title: str
    body: str
    links: list[str] = field(default_factory=list)
    media: list[str] = field(default_factory=list)
    forwarded_from: str | None = None
    views: int = 0
    labels: list[str] = field(default_factory=list)
    narratives: list[str] = field(default_factory=list)
    followers: int = 0
    window: str | None = None
    probe: bool = False
    vec: list[float] | None = None
    sh: frozenset = frozenset()
    url_n: str = ""
    links_n: frozenset = frozenset()
    media_k: frozenset = frozenset()

    def __post_init__(self):
        self.sh = shingles(f"{self.title} {self.body}")
        self.url_n = norm_url(self.url) if self.url else ""
        self.links_n = frozenset(norm_url(u) for u in self.links if u)
        self.media_k = frozenset(k for k in (media_key(u) for u in self.media) if k)

    @property
    def date_only(self) -> bool:
        """Some outlets publish a date without a time (stored as local or UTC midnight)."""
        p = self.published_at
        return bool(p and p.minute == 0 and p.second == 0 and p.microsecond == 0 and p.hour in (0, 22, 23))

    @property
    def when(self) -> datetime | None:
        """When the post appeared. A date-only post is placed at the end of its day, so it never beats a same-day
        post with a real time; one with no date at all uses the time Parse first saw it."""
        if self.date_only:
            return self.published_at + timedelta(hours=23, minutes=59)
        return self.published_at or self.first_seen_at

    @property
    def family(self) -> str:
        return LANG_FAMILY.get(self.lang or "", self.lang or "?")


def norm_url(u: str) -> str:
    p = urlparse(u.strip())
    host = (p.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    return f"{host}{p.path.rstrip('/')}"


def media_key(u: str) -> str | None:
    """Same picture, re-hosted or resized: compare the file name, ignoring size suffixes and query strings."""
    p = urlparse(u)
    name = p.path.rsplit("/", 1)[-1].lower()
    name = re.sub(r"[-_](\d{2,4}x\d{2,4}|scaled|large|medium|small|thumb)(?=\.)", "", name)
    stem = name.rsplit(".", 1)[0]
    if len(stem) < 8 or stem in ("default", "placeholder", "logo", "share", "og-image", "image"):
        return None
    return name


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", fold(text or ""))


def shingles(text: str, k: int = 4) -> frozenset:
    t = tokens(text)
    if len(t) < k:
        return frozenset([" ".join(t)]) if t else frozenset()
    return frozenset(" ".join(t[i:i + k]) for i in range(len(t) - k + 1))


def overlap(a: frozenset, b: frozenset) -> tuple[int, float, float]:
    """Shared 4-word phrases, Jaccard, and containment (share of the shorter text found in the other)."""
    if not a or not b:
        return 0, 0.0, 0.0
    inter = len(a & b)
    return inter, inter / len(a | b), inter / min(len(a), len(b))


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b:
        return 0.0
    return sum(x * y for x, y in zip(a, b))   # vectors are normalised by the embedder


def _before(a: Node, b: Node) -> bool:
    """a was published before b. Undated posts sort after dated ones; ties go by id so the order is stable."""
    if a.when and b.when:
        return (a.when, a.id) < (b.when, b.id)
    if a.when or b.when:
        return bool(a.when)
    return a.id < b.id


def pair_edge(a: Node, b: Node, c: dict, common_media: frozenset = frozenset(),
              nav_links: frozenset = frozenset()) -> dict | None:
    """The strongest typed edge from earlier post a to later post b, or None. Section 10 step 3."""
    if a.when and b.when and b.when - a.when > timedelta(days=c["max_edge_gap_days"]):
        return None
    found = []
    if b.forwarded_from and b.forwarded_from in (a.source_id, a.url_n):
        found.append(("forward", 1.0, "forwarded_from"))
    if a.url_n and a.url_n in b.links_n and (b.source_id, a.url_n) not in nav_links:
        found.append(("link", 1.0, "outgoing link"))
    shared_media = (a.media_k & b.media_k) - common_media
    if shared_media and a.source_id != b.source_id:
        found.append(("copy", 1.0, "same image"))
    inter, jac, cont = overlap(a.sh, b.sh)
    # Two articles from one outlet share its template (bylines, "read also", footers): demand much more overlap.
    if a.source_id == b.source_id:
        jac, cont = (jac if jac >= 0.6 else 0.0), (cont if cont >= 0.8 else 0.0)
    if jac >= c["copy_jaccard"]:
        found.append(("copy", round(jac, 3), "shared wording"))
    elif cont >= c["quote_containment"] and inter >= c["quote_min_shared"]:
        found.append(("quote", round(cont, 3), "quoted passage"))
    if a.family != b.family:
        cs = cosine(a.vec, b.vec)
        if cs >= c["translate_cosine"]:
            found.append(("translate", round(cs, 3), f"{a.lang}→{b.lang}"))
    if not found:
        return None
    typ, sim, via = max(found, key=lambda f: (EDGE_RANK[f[0]], f[1]))
    e = {"from": a.id, "to": b.id, "type": typ, "sim": sim, "via": via}
    if typ not in ("link", "forward") and (a.date_only or b.date_only):
        e["order_uncertain"] = True   # a date without a time: which came first that day is not known
    return e


def common_media_keys(nodes: list[Node], c: dict) -> frozenset:
    """Images that appear on many posts (logos, default share images) prove nothing."""
    cnt = Counter(k for n in nodes for k in n.media_k)
    lim = max(3, int(len(nodes) * c["common_media_share"]))
    per_src = defaultdict(set)
    for n in nodes:
        for k in n.media_k:
            per_src[k].add(n.source_id)
    return frozenset(k for k, v in cnt.items() if v > lim or (v >= 3 and len(per_src[k]) == 1))


def nav_links_of(nodes: list[Node], k: int = 3) -> frozenset:
    """(outlet, page) pairs where the outlet links to its own page from k+ posts: a sidebar or "most read" widget,
    not evidence that the page is where the story came from."""
    cnt = Counter((n.source_id, u) for n in nodes for u in n.links_n)
    own = defaultdict(set)
    for n in nodes:
        own[n.source_id].add(n.url_n)
    return frozenset(key for key, v in cnt.items() if v >= k and key[1] in own[key[0]])


def build_graph(nodes: list[Node], c: dict) -> dict[str, dict]:
    """For each post, its best inbound edge (its parent). The result is a forest: one tree per origin group."""
    common = common_media_keys(nodes, c)
    nav = nav_links_of(nodes)
    order = sorted(nodes, key=lambda n: (n.when is None, n.when or datetime.min.replace(tzinfo=timezone.utc), n.id))
    parent: dict[str, dict] = {}
    for j, b in enumerate(order):
        best = None
        for a in order[:j]:
            if a.probe or not _before(a, b):   # pasted text is the newest thing in the trace, never a parent
                continue
            e = pair_edge(a, b, c, common, nav)
            if e and (best is None or (EDGE_RANK[e["type"]], e["sim"]) > (EDGE_RANK[best["type"]], best["sim"])):
                best = e
        if best:
            parent[b.id] = best
    return parent


def groups_of(nodes: list[Node], parent: dict[str, dict]) -> dict[str, str]:
    """node id -> root id of its tree. Reposts of one original share a root, so they count once."""
    root = {}

    def find(i: str) -> str:
        path = []
        while i in parent and i not in root:
            path.append(i)
            i = parent[i]["from"]
        r = root.get(i, i)
        for p in path:
            root[p] = r
        root[i] = r
        return r

    return {n.id: find(n.id) for n in nodes}


def children_of(parent: dict[str, dict]) -> dict[str, list[str]]:
    ch = defaultdict(list)
    for b, e in parent.items():
        ch[e["from"]].append(b)
    return ch


def descendants(nid: str, ch: dict[str, list[str]], src: dict[str, str] | None = None) -> int:
    """Later posts that descend from this one. With `src` (id -> source), only posts by other sources count:
    an outlet linking to its own earlier article is follow-up, not amplification."""
    n, stack = 0, list(ch.get(nid, []))
    while stack:
        x = stack.pop()
        if src is None or src.get(x) != src.get(nid):
            n += 1
        stack.extend(ch.get(x, []))
    return n


def depth_of(nid: str, parent: dict[str, dict]) -> int:
    d = 0
    while nid in parent and d < 500:
        nid = parent[nid]["from"]
        d += 1
    return d


def pick_origin(nodes: list[Node], parent: dict[str, dict], group: dict[str, str], c: dict,
                seed_id: str | None = None, story_terms: list[str] | None = None, seed_title: str = "") -> dict:
    """Section 10 step 4: earliest published node with no inbound edge, and how far to trust it.

    A root counts only if it is where the seed's own chain begins, or some post in its origin group names the story
    in its headline (2+ distinct names from the seed's search words): an earlier post about something else in the
    same place (even one that was copied) is context, not the origin. Without search words: the group must spread."""
    real = [n for n in nodes if not n.probe]
    roots = sorted((n for n in real if n.id not in parent),
                   key=lambda n: (n.published_at is None, n.when or datetime.max.replace(tzinfo=timezone.utc)))
    size = Counter(group.values())
    seed_root = group.get(seed_id) if seed_id else None
    all_roots = roots
    terms = set(story_terms or [])

    # words next to each other in the seed's headline are one name ("Zubin Potok" counts once)
    seq = [stem(fold(w)) for w in re.findall(r"[^\W\d_]+", seed_title)]
    name_of = {}
    for i, w in enumerate(seq):
        name_of.setdefault(w, name_of.get(seq[i - 1], i) if i and seq[i - 1] in terms and w in terms else i)

    def names_story(n: Node) -> bool:
        hit = {stem(fold(w)) for w in re.findall(r"[^\W\d_]{4,}", n.title)} & terms
        return len({name_of.get(w, w) for w in hit}) >= 2

    if terms:
        named = {group.get(n.id, n.id) for n in real if names_story(n)}
        roots = [n for n in roots if n.id == seed_root or n.id in named] or roots
    else:
        roots = [n for n in roots if size[n.id] > 1 or n.id == seed_root] or roots
    if not roots:
        return {"signal_id": None, "confidence": 0.0, "method": "earliest_observed", "reasons": ["No posts to trace."]}
    o = roots[0]
    conf, reasons = 0.9, []
    if o.published_at is None:
        conf -= 0.3
        reasons.append("−0.30 · it has no publish time; Parse used the time it first saw the post")
    if o.date_only:
        conf -= 0.2
        reasons.append("−0.20 · its outlet gives a date but no time, so its order within that day is unknown")
    if o.platform == "mirror":
        conf -= 0.25
        reasons.append("−0.25 · it is a mirror site, which republishes material from elsewhere")
    if size[o.id] == 1 and len(real) > 1:
        conf -= 0.1
        reasons.append("−0.10 · nothing else in the trace copies, quotes or links to it")
    nxt = next((n for n in all_roots if n is not o and n.when and o.when and n.when >= o.when), None)
    if nxt is not None:
        gap = (nxt.when - o.when).total_seconds() / 60
        if gap <= c["ambiguous_origin_minutes"]:
            conf -= 0.15
            reasons.append(f"−0.15 · another independent post ({nxt.source}) appeared {gap:.0f} min later")
    conf -= 0.1
    reasons.append("−0.10 · Parse only sees its registry; X, Facebook and TikTok are Phase 2, so an earlier post "
                   "may exist outside the archive")
    return {"signal_id": o.id, "confidence": round(max(0.05, min(0.95, conf)), 2), "method": "earliest_observed",
            "reasons": reasons, "runner_up": nxt.id if nxt is not None else (roots[1].id if len(roots) > 1 else None)}


def amplifiers(nodes: list[Node], parent: dict[str, dict], origin_id: str | None) -> list[dict]:
    """Section 10 step 5: rank sources by how many later posts descend from theirs (downstream reach)."""
    ch = children_of(parent)
    src = {n.id: n.source_id for n in nodes}
    by_src: dict[str, dict] = {}
    for n in nodes:
        if n.probe or n.id == origin_id:
            continue
        r = descendants(n.id, ch, src)
        a = by_src.setdefault(n.source_id, {"source_id": n.source_id, "source": n.source, "tier": n.tier,
                                            "platform": n.platform, "posts": 0, "reach": 0, "passed_on": 0,
                                            "views": 0, "first": n.when, "signal_id": n.id})
        a["posts"] += 1
        a["reach"] += r
        a["passed_on"] += 1 if r else 0
        a["views"] += n.views
        if n.when and (a["first"] is None or n.when < a["first"]):
            a["first"], a["signal_id"] = n.when, n.id
    out = sorted(by_src.values(), key=lambda a: (-a["reach"], -a["posts"], a["first"] or datetime.max.replace(
        tzinfo=timezone.utc)))
    return out


# ---------------------------------------------------------------- discovery (step 6)
IGNORE_HOSTS = ("google.", "wikipedia.org", "wikimedia.org", "gstatic.com", "googleapis.com", "doubleclick.net",
                "schema.org", "w3.org", "wordpress.org", "gravatar.com", "apple.com", "play.google", "bit.ly",
                "creativecommons.org", "addtoany.com", "sharethis.com", "whatsapp.com", "viber.com", "mailto")
SHARE_PATHS = ("/sharer", "/share", "/intent/", "/dialog/", "/hashtag/", "/login", "/signup")


def upstream_of(url: str) -> str | None:
    """Channel- or site-level address for a link, or None when the link is not a plausible source."""
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if not host or p.scheme not in ("http", "https") or any(h in host for h in IGNORE_HOSTS):
        return None
    if any(s in p.path.lower() for s in SHARE_PATHS):
        return None
    host = host[4:] if host.startswith("www.") else host
    parts = [x for x in p.path.split("/") if x]
    if host in ("t.me", "telegram.me") and parts:
        ch = parts[1] if parts[0] == "s" and len(parts) > 1 else parts[0]
        return f"https://t.me/s/{ch}"
    if host in ("x.com", "twitter.com", "mobile.twitter.com") and parts:
        return f"https://x.com/{parts[0]}" if parts[0] not in ("i", "home", "search") else None
    if host in ("facebook.com", "m.facebook.com", "instagram.com", "tiktok.com", "youtube.com") and parts:
        return f"https://{host}/{parts[0]}" if parts[0] not in ("watch", "share", "p", "reel", "photo.php") else None
    return f"https://{host}/"


# ---------------------------------------------------------------- the brief (deterministic)
def _fmt(d: datetime | None) -> str:
    return f"{d:%d %b %Y, %H:%M} UTC" if d else "an unknown time"


def _span(a: datetime | None, b: datetime | None) -> str:
    return _dur(b - a) if a and b else "an unknown period"


def _dur(td: timedelta) -> str:
    h = td.total_seconds() / 3600
    return f"{h * 60:.0f} minutes" if h < 1 else (f"{h:.1f} hours" if h < 48 else f"{h / 24:.1f} days")


def topic_terms(nodes: list[Node], n: int = 6) -> list[str]:
    """Words the story's posts share most, for the 'what this is about' line."""
    df = Counter()
    for x in nodes:
        df.update({t for t in tokens(x.title) if len(t) > 4 and t not in STOP_TERMS})
    return [t for t, k in df.most_common(n) if k > 1] or [t for t, _ in df.most_common(3)]


# ---------------------------------------------------------------- database side
def count(v) -> int:
    """Engagement numbers arrive as 5400, "5400", "6.48K" or "1.2M"."""
    if v in (None, ""):
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    m = re.match(r"\s*([\d.,]+)\s*([KkMm]?)", str(v))
    if not m:
        return 0
    try:
        n = float(m.group(1).replace(",", ""))
    except ValueError:
        return 0
    return int(n * {"k": 1e3, "m": 1e6}.get(m.group(2).lower(), 1))


def _node_from(sig: Signal, src: Source) -> Node:
    eng = sig.engagement or {}
    return Node(id=sig.signal_id, source_id=src.source_id, source=src.name, tier=src.tier, platform=sig.platform,
                lang=sig.lang, published_at=sig.published_at, first_seen_at=sig.first_seen_at, url=sig.url,
                title=sig.title or "", body=(sig.text_latin or sig.text_original or "")[:6000],
                links=list(sig.links_out or []), media=[m.get("url") for m in (sig.media or []) if m.get("url")],
                forwarded_from=sig.forwarded_from, views=count(eng.get("views")), labels=list(sig.labels or []),
                narratives=list(sig.narratives or []), followers=int(sig.author_followers or 0), window=sig.window)


def stem(word: str) -> str:
    """First five letters of a long word, so Serbian and Albanian forms of a name meet:
    Lepenac / Lepencit -> lepen, Varage / Varagë -> varag, kanala / kanali -> kanal."""
    return word[:5] if len(word) >= 6 else word


def seed_terms(text: str, title: str = "", avoid: str = "", k: int = 6) -> list[str]:
    """Distinctive words to search for, as stems: the title's words first, names and places (capitalised) next.

    `avoid` holds the outlet's own name, which appears in its boilerplate and says nothing about the story."""
    from parse.web.ask import STOP
    skip = set(tokens(avoid)) | STOP | STOP_TERMS
    score: dict[str, float] = {}
    for weight, part in ((3.0, title), (1.0, (text or "")[:3000])):
        words = re.findall(r"[^\W\d_]{4,}", part or "")
        for i, w in enumerate(words):
            f = fold(w)
            if f in skip or stem(f) in skip:
                continue
            caps = w[0].isupper() and (weight > 1 or (i and not words[i - 1].endswith(".")))
            sc = weight + (1.5 if caps else 0) + min(len(f), 10) / 10
            st = stem(f)
            score[st] = max(score.get(st, 0), sc) + 0.2   # repeated words count a little more
    return [w for w, _ in sorted(score.items(), key=lambda kv: -kv[1])[:k]]


def _search(s, terms: list[str], around: datetime | None, days: int, limit: int, need: int,
            until: datetime | None = None) -> list[tuple]:
    """Signals matching at least `need` of the terms, closest to `around` first (newest first without it)."""
    from parse.web.ask import term_regex
    blob = func.concat_ws(" ", Signal.title, Signal.text_latin, Signal.text_original, Signal.text_en)
    hits = sum((cast(blob.op("~*")(term_regex(t)), Integer) for t in terms), start=0)
    q = select(Signal, Source, hits.label("hits")).join(Source).where(hits >= need)
    if until:   # replay: only what had been published by then
        q = q.where(Signal.published_at <= until)
    if around:
        q = q.where(Signal.published_at.between(around - timedelta(days=days), around + timedelta(days=days)))
        q = q.order_by(hits.desc(), func.abs(func.extract("epoch", Signal.published_at - around)))
    else:
        q = q.order_by(hits.desc(), Signal.published_at.desc().nulls_last())
    return s.execute(q.limit(limit)).all()


def diverse_cut(nodes: list[Node], k: int, seed: Node, key) -> list[Node]:
    """Keep the k best candidates, taking turns between languages so Albanian, Serbian and other coverage of the
    same story all reach the graph (word matches favour the seed's own language)."""
    fam = defaultdict(list)
    for n in sorted(nodes, key=key):
        if n is not seed:
            fam[n.family].append(n)
    out, queues = [seed], sorted(fam.values(), key=lambda q: (q[0].family != seed.family, -len(q)))
    while len(out) < k and any(queues):
        for q in queues:
            if q and len(out) < k:
                out.append(q.pop(0))
    return out


def _nearest(s, vec: list[float], around: datetime | None, days: int, limit: int,
             until: datetime | None = None) -> list[tuple]:
    """Posts closest in meaning to the seed, in any language, among those Parse has already embedded."""
    q = select(Signal, Source, Signal.embedding.cosine_distance(vec).label("d")).join(Source).where(
        Signal.embedding.is_not(None))
    if until:
        q = q.where(Signal.published_at <= until)
    if around:
        q = q.where(Signal.published_at.between(around - timedelta(days=days), around + timedelta(days=days)))
    return [(a, b) for a, b, d in s.execute(q.order_by("d").limit(limit)).all() if d <= 0.35]


def _embed(nodes: list[Node]) -> tuple[int, int, str | None]:
    """Fill vectors: reuse stored embeddings, compute the missing ones locally and store them. Returns (reused, new)."""
    from parse import budget
    from parse.llm import embed_texts
    from parse.normalise.embed import MAX_CHARS
    ids = [n.id for n in nodes if not n.probe]
    with session() as s:
        have = {sid: list(v) for sid, v in s.execute(select(Signal.signal_id, Signal.embedding).where(
            Signal.signal_id.in_(ids), Signal.embedding.is_not(None))).all()}
    todo = [n for n in nodes if n.id not in have]
    if todo:
        with session() as s:
            raw = {sid: (t, x) for sid, t, x in s.execute(select(Signal.signal_id, Signal.title, Signal.text_original)
                                                           .where(Signal.signal_id.in_([n.id for n in todo])))}
        texts = ["\n".join(t for t in raw.get(n.id, (n.title, n.body)) if t)[:MAX_CHARS] if not n.probe
                 else f"{n.title}\n{n.body}"[:MAX_CHARS] for n in todo]
        vecs = embed_texts(texts)
        with session() as s:
            for n, v in zip(todo, vecs):
                n.vec = v
                if not n.probe:
                    s.get(Signal, n.id).embedding = v
    for n in nodes:
        if n.id in have:
            n.vec = have[n.id]
    try:
        model = budget.model("embedding")["id"]
    except Exception:  # noqa: BLE001
        model = None
    return len(have), len([n for n in todo if not n.probe]), model


def _baseline(s, terms: list[str], start: datetime, weeks: int = 4) -> list[int]:
    """How many posts matched the same words in the same hour of the week, in each of the weeks before."""
    from parse.web.ask import term_regex
    blob = func.concat_ws(" ", Signal.title, Signal.text_latin, Signal.text_original)
    cond = or_(*[blob.op("~*")(term_regex(t)) for t in terms[:3]])
    out = []
    for w in range(1, weeks + 1):
        a = start - timedelta(weeks=w)
        out.append(s.scalar(select(func.count()).select_from(Signal).where(
            cond, Signal.published_at.between(a, a + timedelta(hours=1)))) or 0)
    return out


def _scope_match(scope: str | None, claim: str) -> str | None:
    """Tier 0 only counts as Tier 0 inside its own scope. Match the institution named in the scope to the claim."""
    if not scope:
        return None
    generic = {"own", "only", "statements", "operations", "announcements", "deployments", "activities", "decisions",
               "notifications", "government", "ministry"}
    words = [w for w in tokens(scope.replace("'s", "")) if len(w) >= 3 and w not in generic]
    c = fold(claim)
    hit = next((w for w in words if re.search(rf"\b{re.escape(w)}", c)), None)
    return hit


class TraceError(RuntimeError):
    """A seed could not be traced, in a sentence the page can show."""


def _ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 1)


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


def _read_image(data_url: str) -> tuple[str, dict]:
    """OCR a screenshot: Tesseract on this machine first (free); the image model only if that finds no text."""
    import io

    from PIL import Image

    from parse.normalise import media
    m = re.match(r"data:(image/[\w.+-]+);base64,(.*)", data_url or "", re.S)
    if not m:
        raise TraceError("The screenshot must be a PNG, JPEG or WebP image.")
    raw = base64.b64decode(m.group(2))
    if len(raw) > 8_000_000:
        raise TraceError("The screenshot is larger than 8 MB.")
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as e:  # noqa: BLE001
        raise TraceError("That file is not an image Parse can read.") from e
    text = media.ocr(img)
    info = {"engine": "tesseract (local, free)", "chars": len(text), "phash": media.phash(img), "usd": 0.0}
    if len(text.strip()) >= media.MIN_TESSERACT_CHARS:
        return text, info
    from parse.web import models_live as ml
    if not ml.key_set():
        raise TraceError("Tesseract found no text in the screenshot, and the image model needs FEATHERLESS_API_KEY.")
    try:
        text, usage = ml.client().ocr_image("ocr_fallback", "trace-ocr", raw, m.group(1))
    except Exception as e:  # noqa: BLE001
        raise TraceError(ml.explain(e)) from e
    from parse import budget
    info.update(engine=budget.model("ocr_fallback")["id"], chars=len(text), usd=usage.get("usd", 0.0))
    return text, info


def _fetch_url(url: str) -> tuple[Signal | None, str, dict]:
    """A link: use the archived copy if Parse has it; otherwise fetch it through the registry gate and archive it."""
    from parse.collectors.emit import emit, published_from_html
    from parse.fetch import Fetcher
    from parse.registry import RegistryGateError, gate
    with session() as s:
        hit = s.scalar(select(Signal).where(or_(Signal.url == url, Signal.url == url.rstrip("/"),
                                                Signal.url == url.rstrip("/") + "/")))
        if hit is not None:
            return hit, "", {"how": "already in the archive", "signal_id": hit.signal_id}
    with session() as s:
        try:
            src = gate(s, url, actor="A12-tracer")
        except RegistryGateError as e:
            raise TraceError(f"Parse only fetches registry sources ({e}). Paste the post's text instead.") from e
    f = Fetcher(min_delay=1.0, timeout=15.0)
    if not f.robots_allows(url):
        raise TraceError("The site's robots.txt does not allow fetching this page. Paste the post's text instead.")
    with session() as s:
        r = f.get(s, url, actor="A12-tracer")
    if r.status_code != 200:
        raise TraceError(f"The page answered HTTP {r.status_code}.")
    import trafilatura
    doc = trafilatura.bare_extraction(r.text, url=url, with_metadata=True)
    doc = doc.as_dict() if hasattr(doc, "as_dict") else (doc or {})
    text, title = doc.get("text") or "", doc.get("title")
    if len(text) < 40:
        raise TraceError("Parse could not find the article text on that page. Paste the post's text instead.")
    with session() as s:
        src = s.get(Source, src.source_id)
        sig = emit(s, src, url=url, raw=r.content, content_type=r.headers.get("content-type", "text/html"),
                   title=title, text=text, published_at=published_from_html(r.content), agent="A12-tracer",
                   method="trace-fetch")
        sid = sig.signal_id if sig else None
    with session() as s:
        sig = s.get(Signal, sid) if sid else s.scalar(select(Signal).where(Signal.url == url))
    return sig, text, {"how": f"fetched from {src.name} and archived", "signal_id": sig.signal_id if sig else None}


def _resolve_seed(seed: dict) -> tuple[Node | None, Signal | None, str, dict]:
    """Returns (probe node or None, seed signal or None, seed text, info about how the seed was read)."""
    kind = seed.get("kind")
    info: dict = {"kind": kind}
    if kind == "signal":
        with session() as s:
            row = s.execute(select(Signal, Source).join(Source).where(Signal.signal_id == seed.get("signal_id"))).first()
        if row is None:
            raise TraceError("That signal is not in the archive.")
        return None, row[0], f"{row[0].title or ''}\n{row[0].text_latin or row[0].text_original or ''}", info
    if kind == "url":
        sig, _, more = _fetch_url(str(seed.get("url", "")).strip())
        info.update(more)
        if sig is None:
            raise TraceError("The page could not be archived.")
        return None, sig, f"{sig.title or ''}\n{sig.text_latin or sig.text_original or ''}", info
    if kind == "image":
        text, more = _read_image(seed.get("image", ""))
        info.update(more, ocr_text=text[:2000])
    else:
        text = str(seed.get("text", ""))
    text = text.strip()[:6000]
    if len(re.findall(r"[^\W\d_]{3,}", text)) < 3:
        raise TraceError("Need at least a sentence of text to trace (names, places, what happened).")
    first = text.split("\n", 1)
    probe = Node(id=PROBE_ID, source_id="probe", source="Your " + ("screenshot" if kind == "image" else "text"),
                 tier=3, platform="probe", lang=None, published_at=None, first_seen_at=None, url="",
                 title=first[0][:200], body=text, probe=True)
    try:
        from parse.normalise.text import detect_lang
        probe.lang = detect_lang(text)
    except Exception:  # noqa: BLE001
        pass
    return probe, None, text, info


# ---------------------------------------------------------------- the run
def run(seed: dict, ai: bool = False, fresh: bool = False, persist: bool = True, until: datetime | None = None,
        event_id: str | None = None) -> Iterator[dict]:
    """Trace one seed. Yields one dict per Section 10 step as it finishes, then {"type": "result", ...}.

    until: trace as of this moment (the Watcher's replay never sees later posts).
    event_id: update that Event in place (the Watcher keeps one Event per story) instead of adding a new one."""
    c = cfg()
    t_all = time.perf_counter()

    log: list[dict] = []   # every step, kept with the result so a saved trace reopens as it ran

    def step(sid: str, t0: float, **kw) -> dict:
        d = {"type": "step", "id": sid, "ms": _ms(t0), **kw}
        log.append(d)
        return d

    # 1. seed ------------------------------------------------------------------------------------------------------
    t0 = time.perf_counter()
    try:
        probe, seed_sig, seed_text, info = _resolve_seed(seed)
    except TraceError as e:
        yield step("seed", t0, n=1, title="Seed", status="error", summary=str(e), rows=[])
        yield {"type": "error", "message": str(e)}
        return
    if seed_sig is not None:
        with session() as s:
            src0 = s.get(Source, seed_sig.source_id)
            avoid = f"{src0.name} {urlparse(src0.url or '').hostname or ''}"
        terms = seed_terms(seed_sig.text_latin or seed_sig.text_original or "", seed_sig.title or "", avoid)
    else:
        terms = seed_terms(seed_text, seed_text.split("\n", 1)[0][:200])
    anchor = seed_sig.published_at if seed_sig else None
    rows = [["started from", {"signal": "a signal in the archive", "url": "a link", "image": "a screenshot",
                              "text": "pasted text"}.get(info["kind"], "text")]]
    if info.get("how"):
        rows.append(["link", info["how"]])
    if info["kind"] == "image":
        rows += [["read with", info["engine"]], ["text found", f"{info['chars']} characters"],
                 ["image pHash", info["phash"]]]
    rows.append(["search words", ", ".join(terms) or "none"])
    yield step("seed", t0, n=1, title="Seed", status="ok" if terms else "error",
               summary=(seed_sig.title if seed_sig else seed_text[:160]) or "(untitled)", rows=rows,
               explain="What we are tracing. A post from the archive, a link, a screenshot or pasted text. "
                       "Parse picks the distinctive words (names, places) to search for.",
               ocr=info.get("ocr_text"), ai={"state": "used" if info.get("usd") else "none",
                                            "what": f"Text read by {info.get('engine')}" if info["kind"] == "image"
                                            else "No model."})
    if not terms:
        yield {"type": "error", "message": "No distinctive words to search for. Add names, places or what happened."}
        return

    # 1b. field agents: newer reports into the archive before tracing
    if fresh:
        from parse.web.ask import _agents_step
        ag = _agents_step(terms[:4])
        ag["id"], ag["n"] = "agents", 1
        log.append(ag)
        yield ag

    # 2. expand ----------------------------------------------------------------------------------------------------
    t0 = time.perf_counter()
    with session() as s:
        seed_node = probe or _node_from(seed_sig, s.get(Source, seed_sig.source_id))
    seed_node._hits = 99   # noqa: SLF001
    try:
        _embed([seed_node])
    except Exception:  # noqa: BLE001 - no embedder: links, images and wording still work
        pass
    with session() as s:
        need = 2 if len(terms) >= 3 else 1
        found = _search(s, terms, anchor, c["search_days"], c["max_candidates"], need, until)
        if len(found) < 5 and need > 1:
            need = 1
            found = _search(s, terms, anchor, c["search_days"], c["max_candidates"], 1, until)
        twin = None
        if probe is not None and found:
            # Pasted text has no date. Find the archived post it matches best (its "twin"), then search again
            # around that post's date so the candidates are the story's own week, not every year that shares words.
            scored = [(overlap(probe.sh, shingles(f"{sg.title or ''} {(sg.text_latin or sg.text_original or '')[:6000]}"))[2],
                       h, sg, sr) for sg, sr, h in found if sg.published_at]
            top = max((x[0] for x in scored), default=0.0)
            # among the posts that match the text (nearly) best, the earliest is the original; later ones quote it
            close = [x for x in scored if x[0] >= max(0.3, top * 0.85)]
            best = min(close, key=lambda x: x[2].published_at) if close else (0.0, 0, None, None)
            if best[0] >= 0.3:
                twin = _node_from(best[2], best[3])
                anchor = best[2].published_at
                found = _search(s, terms, anchor, c["search_days"], c["max_candidates"], need, until)
        cand = {sg.signal_id: _node_from(sg, sr) for sg, sr, _ in found}
        if twin is not None:
            cand.setdefault(twin.id, twin)
        for (sg, _, h) in found:
            cand[sg.signal_id]._hits = h   # noqa: SLF001
        by_vec = []
        if seed_node.vec is not None:
            for sg, sr in _nearest(s, seed_node.vec, anchor, c["search_days"], 60, until):
                if sg.signal_id not in cand:
                    cand[sg.signal_id] = _node_from(sg, sr)
                    cand[sg.signal_id]._hits = need   # noqa: SLF001
                    by_vec.append(sg.signal_id)
        if seed_sig is not None:
            cand[seed_sig.signal_id] = seed_node
        # follow links backwards: posts the candidates link to, if Parse archived them
        linked = {u for n in cand.values() for u in n.links if u}
        by_link = []
        if linked:
            for sg, sr in s.execute(select(Signal, Source).join(Source).where(Signal.url.in_(list(linked)[:800]))).all():
                if sg.signal_id not in cand and not (until and sg.published_at and sg.published_at > until):
                    cand[sg.signal_id] = _node_from(sg, sr)
                    cand[sg.signal_id]._hits = need   # noqa: SLF001
                    by_link.append(sg.signal_id)
    nodes = list(cand.values()) + ([probe] if probe else [])
    for n in nodes:   # rank by likeness to the seed (shared phrases, then search words) and keep the closest
        n._ov = 1.0 if n is seed_node else overlap(seed_node.sh, n.sh)[2]   # noqa: SLF001
    nodes = diverse_cut(nodes, c["max_nodes"] + 1, seed_node,
                        key=lambda n: (-(n._ov >= c["member_overlap"]), -n._hits, -n._ov))   # noqa: SLF001
    try:
        reused, new, emb_model = _embed(nodes)
        emb_note = f"{reused} stored, {new} computed now on this machine"
    except Exception as e:  # noqa: BLE001 - without vectors the trace still runs on links, images and wording
        reused, new, emb_model = 0, 0, None
        emb_note = f"skipped ({type(e).__name__}); translate edges need it"
    twin = cand.get(twin.id) if twin is not None else None
    members = []
    for n in nodes:
        # a short pasted headline compares poorly with whole articles, so its archived twin also counts
        n._cos = max(cosine(seed_node.vec, n.vec), cosine(twin.vec, n.vec) if twin is not None else 0.0)   # noqa: SLF001
        bar = c["member_cosine"] if n.family == seed_node.family else c["member_cosine_cross"]
        if n is seed_node or n._ov >= c["member_overlap"] or n._cos >= bar:
            members.append(n)
    # Expand backwards, but not into older, different events at the same place: a post from well before the seed
    # stays only if a post in the story links or forwards to it (explicit evidence it is upstream).
    ref_t = (twin.when if twin is not None else None) or (seed_node.when if not seed_node.probe else None)
    if ref_t:
        floor = ref_t - timedelta(hours=c["lookback_hours"])
        link_floor = ref_t - timedelta(days=c["max_edge_gap_days"])
        members = [n for n in members if n.probe or n is seed_node or not n.when or n.when >= floor
                   or (n.id in by_link and n.when >= link_floor)]
    if anchor is None:   # pasted text: centre the story on the closest archived post
        best = max((n for n in members if not n.probe and n.when), key=lambda n: (n._ov, n._cos), default=None)
        if best:
            lo, hi = best.when - timedelta(days=c["search_days"]), best.when + timedelta(days=c["search_days"])
            members = [n for n in members if n.probe or not n.when or lo <= n.when <= hi]
    nodes = members
    real = [n for n in nodes if not n.probe]
    yield step("expand", t0, n=2, title="Expand backwards", status="ok" if real else "empty",
               summary=f"{len(real)} posts in this story, from {len(found)} archive matches",
               rows=[["word search", f"{len(found)} posts match {need}+ of: {', '.join(terms)}"],
                     ["window", f"±{c['search_days']} days around "
                                + (_fmt(anchor) if anchor else "the closest match")
                                + (f" (your text matches {twin.source}: “{twin.title[:80]}”)" if twin is not None else "")],
                     ["meaning search", f"{len(by_vec)} more posts close in meaning, any language"],
                     ["followed links", f"{len(by_link)} linked posts pulled in from the archive"],
                     ["embeddings", f"{emb_note} ({emb_model or 'none'})"],
                     ["kept", f"{len(real)} posts with ≥{c['member_overlap']:.0%} shared wording, or meaning "
                              f"similarity ≥{c['member_cosine']} (≥{c['member_cosine_cross']} in another language)"]],
               explain="Parse searches its archive for earlier and later posts about the same thing: the same "
                       "distinctive words, links between posts, the same image, and close meaning across languages "
                       "(local embeddings). Posts that are only loosely related are dropped.",
               ai={"state": "used" if emb_model else "none",
                   "what": f"Meaning similarity from {emb_model}, run locally for free." if emb_model else "No model."})
    if not real:
        yield {"type": "error", "message": "Nothing in the archive matches this story yet. Try field agents, or "
                                           "paste more of the text (names, places, dates)."}
        return

    # 3. graph -----------------------------------------------------------------------------------------------------
    t0 = time.perf_counter()
    parent = build_graph(nodes, c)
    group = groups_of(nodes, parent)
    et = Counter(e["type"] for e in parent.values())
    n_groups = len({group[n.id] for n in real})
    yield step("graph", t0, n=3, title="Build the graph", status="ok",
               summary=f"{len(parent)} edges · {n_groups} independent origin group{'s' * (n_groups != 1)}",
               rows=[[t, f"{et.get(t, 0)} · {EDGE_HELP[t]}"] for t in EDGE_RANK]
               + [["origin groups", f"{n_groups}: reposts of one original count once"]],
               explain="Each post gets at most one parent: the earlier post it most clearly came from. A forward or "
                       "a link beats shared wording; shared wording beats similar meaning. Posts with no parent "
                       "start their own origin group.",
               ai={"state": "none", "what": "Set overlap and vector arithmetic. No language model."})

    # 4. origin ----------------------------------------------------------------------------------------------------
    t0 = time.perf_counter()
    origin = pick_origin(nodes, parent, group, c, seed_node.id, terms, seed_node.title)
    on = next(n for n in real if n.id == origin["signal_id"])
    depth = {n.id: depth_of(n.id, parent) for n in nodes}
    seed_path = []
    cur = seed_node.id
    while cur in parent and len(seed_path) < 30:
        e = parent[cur]
        seed_path.append(e)
        cur = e["from"]
    seed_root = cur
    yield step("origin", t0, n=4, title="Pick the origin", status="ok",
               summary=f"Earliest observed source: {on.source} · {_fmt(on.when)}",
               rows=[["post", on.title[:140] or on.url], ["source", f"{on.source} · Tier {on.tier} · {on.platform}"],
                     ["published", _fmt(on.published_at) if on.published_at else "unknown (first seen "
                                                                                + _fmt(on.first_seen_at) + ")"],
                     ["confidence", f"{origin['confidence']:.2f}"]] + [["", r] for r in origin["reasons"]],
               explain="The origin is the earliest post with no parent in the graph. It is the earliest *observed* "
                       "source, not proof of who started the story; the confidence says how far to trust it.",
               ai={"state": "none", "what": "Earliest timestamp among roots. No model."})

    # 5. amplifiers ------------------------------------------------------------------------------------------------
    t0 = time.perf_counter()
    amps = amplifiers(nodes, parent, origin["signal_id"])
    with session() as s:
        hist = dict(s.execute(
            select(Signal.source_id, func.count(func.distinct(EventEdge.event_id)))
            .join(Signal, Signal.signal_id == EventEdge.from_signal)
            .where(Signal.source_id.in_([a["source_id"] for a in amps] or [""]))
            .group_by(Signal.source_id)).all())
    for a in amps:
        a["seen_before"] = int(hist.get(a["source_id"], 0))
        a["first"] = _iso(a["first"])
    top_amps = [a for a in amps if a["reach"]][:8]
    yield step("amplifiers", t0, n=5, title="Find the amplifiers", status="ok",
               summary=("Amplified by " + ", ".join(a["source"] for a in top_amps[:3])) if top_amps
               else "No source passed the story on inside the archive",
               table={"cols": ["Source", "Tier", "Posts", "Reach", "Earlier traces"],
                      "rows": [[a["source"], f"T{a['tier']}", a["posts"], a["reach"], a["seen_before"]]
                               for a in amps[:12]]},
               explain="Downstream reach is how many later posts descend from a source's posts in the graph. "
                       "'Earlier traces' counts past traces where the same source passed a story on: sources that "
                       "keep showing up there are how Parse learns the network.",
               ai={"state": "none", "what": "Counting descendants in the graph. No model."})

    # 6. discover --------------------------------------------------------------------------------------------------
    t0 = time.perf_counter()
    from parse.registry import match_source
    with session() as s:
        sources = list(s.scalars(select(Source)))
        cites: dict[str, list[str]] = defaultdict(list)
        for n in real:
            for u in n.links:
                up = upstream_of(u)
                if up and match_source(sources, u) is None and n.id not in cites[up]:
                    cites[up].append(n.id)
        disc = sorted(cites.items(), key=lambda kv: -len(kv[1]))[:15]
        queued_before = set(s.scalars(select(DiscoveryQueue.url).where(
            DiscoveryQueue.url.in_([u for u, _ in disc] or [""]))))
    discovered = [{"url": u, "cited_by": len(ids), "signal_id": ids[0], "new": u not in queued_before}
                  for u, ids in disc]
    yield step("discover", t0, n=6, title="Discover new sources", status="ok" if discovered else "empty",
               summary=(f"{sum(d['new'] for d in discovered)} new upstream sources for the discovery queue"
                        if discovered else "Every linked source is already in the registry"),
               table={"cols": ["Upstream", "Cited by", "Queue"],
                      "rows": [[d["url"], d["cited_by"], "new" if d["new"] else "already queued"] for d in discovered]},
               explain="Posts in this story link to sites and channels that are not in the registry. They go to "
                       "the discovery queue; Parse collects nothing from them until a person approves them.",
               ai={"state": "none", "what": "Reading links. No model."})

    # 7. real world ------------------------------------------------------------------------------------------------
    t0 = time.perf_counter()
    official = [n for n in real if n.tier == 0]
    first_t = min((n.when for n in real if n.when), default=None)
    last_t = max((n.when for n in real if n.when), default=None)
    trig = sig_mod.in_trigger_window(on.when) if on.when else None
    with session() as s:   # official statements about the same words around the same time, even if not copies
        near = []
        if first_t:
            for sg, sr, _ in _search(s, terms, first_t, 3, 40, 1, until):
                if sr.tier == 0 and sg.signal_id not in cand:
                    near.append(_node_from(sg, sr))
    near = near[:5]
    yield step("world", t0, n=7, title="Link to the real world", status="ok",
               summary=f"{len(official)} official post{'s' * (len(official) != 1)} in the story, "
                       f"{len(near)} nearby · " + (f"trigger date: {trig}" if trig else "no trigger date"),
               rows=[["official in story", ", ".join(f"{n.source} ({_fmt(n.when)})" for n in official[:4]) or "none"],
                     ["official nearby", ", ".join(f"{n.source}: {n.title[:60]}" for n in near[:3]) or "none"],
                     ["trigger calendar", trig or "not within a trigger window"]],
               explain="Parse connects the story to official (Tier 0) statements and to dates in the trigger "
                       "calendar (anniversaries that have sparked trouble before).",
               ai={"state": "none", "what": "Lookups. No model."})

    # 8. score -----------------------------------------------------------------------------------------------------
    t0 = time.perf_counter()
    gl = [group[n.id] for n in real]
    f_ind = sig_mod.independent_origins(gl)
    first_by_plat: dict[str, datetime] = {}
    for n in real:
        if n.when and (n.platform not in first_by_plat or n.when < first_by_plat[n.platform]):
            first_by_plat[n.platform] = n.when
    f_cross = sig_mod.cross_platform(first_by_plat)
    nd_win = timedelta(minutes=thresholds()["significance"]["near_duplicate_window_minutes"])
    byid = {n.id: n for n in nodes}
    near_dups = sum(1 for b, e in parent.items() if not byid[b].probe and e["type"] in ("copy", "forward")
                    and e["via"] != "same image" and byid[b].when and byid[e["from"]].when
                    and byid[b].when - byid[e["from"]].when <= nd_win)
    ch = children_of(parent)
    f_coord = sig_mod.coordination(near_dup_share=near_dups / max(len(real), 1), new_account_share=0.0,
                                   max_fanout=max((len(v) for v in ch.values()), default=0))
    dated = sorted(n.when for n in real if n.when)
    peak = max((sum(1 for x in dated[i:] if x - d <= timedelta(hours=1)) for i, d in enumerate(dated)), default=0)
    with session() as s:
        base = _baseline(s, terms, first_t) if first_t else []
    f_vel = sig_mod.velocity_z(peak, base) if base else sig_mod.Feature(0, 0, "No dated posts.")
    f_prox = sig_mod.proximity([f"{n.title} {n.body[:1500]}" for n in real], on.when or datetime.now(timezone.utc))
    label_note = ""
    if ai and not any(n.labels for n in real):
        # Detection: label the origin and the earliest posts with the threat labeller so severity and tripwires
        # have something to work on. Only posts not labelled before are billed.
        from parse.web import models_live as ml
        if ml.key_set():
            pick = [on.id] + [n.id for n in sorted(real, key=lambda n: n.when or datetime.max.replace(
                tzinfo=timezone.utc)) if n.id != on.id][:4]
            try:
                lab = ml.label_many(pick)
                for n in real:
                    if n.id in lab["labels"]:
                        n.labels, n.narratives = list(lab["labels"][n.id][0]), list(lab["labels"][n.id][1])
                label_note = f"{len(pick)} posts labelled ({lab['new']} new, ${lab['usage']['usd']:.5f})"
            except Exception as e:  # noqa: BLE001
                label_note = f"labelling failed: {ml.explain(e)}"
    labels = sorted({l for n in real for l in n.labels})
    narrs = sorted({x for n in real for x in n.narratives})
    followers = sum(n.followers for n in real) or None
    factors = {"severity": tps_mod.severity(labels), "velocity": f_vel.normalised, "reach": tps_mod.reach(followers),
               "coordination": f_coord.normalised, "offline_intent": 0.0, "proximity": f_prox.normalised}
    blob = fold(" ".join(f"{n.title} {n.body[:1500]}" for n in real[:40]))
    has = lambda words: any(fold(w) in blob for w in words)   # noqa: E731
    kw = __import__("parse.settings", fromlist=["keywords"]).keywords()
    trips = tps_mod.tripwires(
        labels=set(labels), narratives=set(narrs),
        has_explosive_term=has(["eksploz", "shpërth", "explos", "detonac", "dinamit", "sabot", "diverzij", "взрыв",
                                "експлоз"]),
        names_critical_site=has(kw["proximity_sensitive"]["infrastructure"]),
        has_weapons_term=has(["oružj", "armë", "weapon", "pušk", "municij", "оруж", "automatsk", "kallashnik"]),
        names_kosovo_place=has(kw["proximity_sensitive"]["north"] + kw["proximity_kosovo_other"]),
        has_time_reference=bool(re.search(r"\b(sot|sonte|danas|večeras|today|tonight|nesër|sutra|tomorrow|"
                                          r"\d{1,2}[:.]\d{2})\b", blob)),
        forged_official_order=False, doxxing_security_staff=False, t8_named_target=False,
        serbian_mod_readiness=False)
    sig_feats = {"velocity_z": f_vel, "independent_origins": f_ind, "cross_platform": f_cross,
                 "coordination": f_coord, "proximity": f_prox}
    best_tier = min(n.tier for n in real)
    yield step("score", t0, n=8, title="Score significance", status="ok",
               summary=f"{n_groups} origin groups · peak {peak}/h · " + f_prox.note[:60],
               rows=[[k, v.note] for k, v in sig_feats.items()]
               + [["labels", ", ".join(labels + narrs) or "none yet (switch the engine to Qwen to label posts)"]]
               + ([["labelling", label_note]] if label_note else [])
               + [["tripwires", "; ".join(trips) or ("none fired" if labels else "need labels (T2/T3/T8) to fire")]],
               explain="How big the story is, separately from whether it is true: speed against its own baseline, "
                       "independent origins, platforms, signs of coordination, and sensitive places or dates.",
               ai={"state": "none", "what": "Statistics from the brief's Section 8. No model."})

    # 9. verify ----------------------------------------------------------------------------------------------------
    t0 = time.perf_counter()
    claim = (seed_text if probe else f"{seed_sig.title or ''}. {(seed_sig.text_en or seed_sig.text_latin or '')[:300]}")
    claim = re.sub(r"\s+", " ", claim).strip()[:500]
    reps: dict[str, Node] = {}
    for n in sorted(real, key=lambda n: (n.tier, n.when or datetime.max.replace(tzinfo=timezone.utc))):
        reps.setdefault(group[n.id], n)
    pool = sorted(reps.values(), key=lambda n: (n.tier, -n._cos))[:c["stance_checks"]] + near[:2]   # noqa: SLF001
    scopes = {}
    if pool:
        with session() as s:
            scopes = dict(s.execute(select(Source.source_id, Source.tier0_scope).where(
                Source.source_id.in_([n.source_id for n in pool]))).all())
    checks, usage_all, stance_note = [], [], ""
    from parse.web import models_live as ml
    can_ai = ai and ml.key_set()
    for i, n in enumerate(pool):
        checks.append({"n": i + 1, "signal_id": n.id, "source": n.source, "tier": n.tier,
                       "group": group.get(n.id, n.id), "title": n.title[:160], "when": _iso(n.when),
                       "stance": "not checked", "confidence": None,
                       "in_scope": _scope_match(scopes.get(n.source_id), claim) if n.tier == 0 else None})
    if can_ai and pool:
        from concurrent.futures import ThreadPoolExecutor

        def one(n: Node):
            try:
                return ml.stance_text(claim, f"{n.title}\n\n{n.body[:3500]}", subject_id=n.id)
            except Exception as e:  # noqa: BLE001
                return e
        with ThreadPoolExecutor(ml.WORKERS) as ex:
            answers = list(ex.map(one, pool))
        for item, r in zip(checks, answers):
            if isinstance(r, Exception):
                stance_note = ml.explain(r)
                continue
            item.update(stance=r["stance"], confidence=round(r["confidence"], 2), model=r["model"])
            usage_all.append(r["usage"])
        if stance_note and not usage_all:
            checks = [c | {"stance": "not checked"} for c in checks]
    if can_ai and not stance_note:
        items = [EvidenceItem(evidence_id=x["signal_id"], stance=x["stance"], tier=x["tier"], origin_group=x["group"],
                              in_tier0_scope=bool(x["in_scope"])) for x in checks]
        v = decide(items)
        verdict = {"verdict": v.verdict, "reason": v.reason, "evidence_ids": v.evidence_ids,
                   "suggested_checks": v.suggested_checks, "checked": True}
    else:
        why = stance_note or ("the answer engine is Parse Retrieval (no model calls)" if not ai
                              else "FEATHERLESS_API_KEY is not set")
        verdict = {"verdict": "UNVERIFIED", "checked": False, "evidence_ids": [],
                   "reason": f"Stance not checked: {why}. Truth and spread are scored apart, so the trace stands.",
                   "suggested_checks": ["Switch the answer engine to Qwen to check the claim against each independent "
                                        "origin group, or read the cited posts below."]}
    verdict["checks"] = checks
    usd = sum(u.get("usd", 0.0) for u in usage_all)
    yield step("verify", t0, n=9, title="Check the claim", status="ok" if verdict["checked"] else "skip",
               summary=f"{verdict['verdict']} · {verdict['reason'][:120]}",
               rows=[["claim", claim[:200]]] + [[f"[{x['n']}] {x['source']} (T{x['tier']})",
                                                 x["stance"] + (f" {x['confidence']:.2f}" if x["confidence"] else "")]
                                                for x in checks],
               explain="One post per independent origin group (best tier first) is compared with the claim. A model "
                       "only says whether each post supports, contradicts or ignores it; the verdict comes from fixed "
                       "rules (CONFIRMED needs Tier 0 inside its own scope; CORROBORATED needs two independent groups).",
               ai={"state": "used" if usage_all else ("available" if not can_ai else "none"),
                   "what": (f"Stance from {checks[0].get('model')} on {len(usage_all)} posts, ${usd:.5f}."
                            if usage_all else "A stance model sits here; it did not run.")})

    # 10. brief ----------------------------------------------------------------------------------------------------
    t0 = time.perf_counter()
    langs = Counter(n.lang or "?" for n in real)
    lang_jump = next(((byid[e["from"]].lang, byid[b].lang, byid[b].when - byid[e["from"]].when)
                      for b, e in sorted(parent.items(), key=lambda kv: byid[kv[0]].when or datetime.max.replace(
                          tzinfo=timezone.utc))
                      if not byid[b].probe and byid[e["from"]].family != byid[b].family and byid[b].when
                      and byid[e["from"]].when), None)
    tps_r = tps_mod.score(factors, tps_mod.credibility(best_tier, verdict["verdict"] if verdict["checked"] else None),
                          trips)
    about = topic_terms(real)
    headline = (f"“{on.title[:110] or 'Untitled post'}” · earliest observed at {on.source} on {_fmt(on.when)}, "
                f"then carried by {len({n.source_id for n in real}) - 1} more outlet(s) over "
                f"{_span(first_t, last_t)}.")
    know = [f"Earliest observed source: {on.source} (Tier {on.tier}, {TIER_NAMES[on.tier].lower()}), "
            f"{_fmt(on.when)}. Confidence {origin['confidence']:.2f}.",
            f"{len(real)} posts from {len({n.source_id for n in real})} sources in "
            + ", ".join(f"{k} {v}" for k, v in langs.most_common(4)) + f"; {n_groups} independent origin group(s).",
            "Spread: " + (", ".join(f"{v} {k}" for k, v in et.most_common()) or "no edges") + " edges"
            + (f"; it crossed from {lang_jump[0]} to {lang_jump[1]} after {_dur(lang_jump[2])}"
               if lang_jump else "") + "."]
    if top_amps:
        know.append("Amplified by " + ", ".join(f"{a['source']} (reach {a['reach']})" for a in top_amps[:4]) + ".")
    if official or near:
        know.append("Official sources: " + ", ".join(sorted({n.source for n in official + near})[:4]) + ".")
    know.append(f"Verdict: {verdict['verdict']}. {verdict['reason']}")
    know.append(f"Priority {tps_r.priority} (TPS {tps_r.tps:.0f}). {tps_r.explanation}")
    dont = ["Whether an earlier post exists outside the registry (X, Facebook, TikTok are Phase 2)."]
    if on.published_at is None:
        dont.append("The origin's exact publish time.")
    if not labels:
        dont.append("Threat labels: the classifier has not run on these posts yet.")
    if not verdict["checked"]:
        dont.append("Whether independent sources support or contradict the claim (stance not checked).")
    if not official and not near:
        dont.append("Any official (Tier 0) statement on it in the archive.")
    checks_todo = list(dict.fromkeys(verdict["suggested_checks"]
                                     + [f"Open the origin post and confirm its timestamp: {on.url}"]
                                     + ([f"Review {sum(d['new'] for d in discovered)} upstream source(s) in the "
                                         "discovery queue."] if any(d["new"] for d in discovered) else [])))
    brief = {"headline": headline, "about": about, "what_we_know": know, "what_we_dont_know": dont,
             "suggested_checks": checks_todo, "writer": "Deterministic templates from the numbers above."}
    ai_brief = None
    if can_ai:
        try:
            ai_brief = ml.write_trace_brief(headline, know, [
                {"n": i + 1, "source": n.source, "tier": n.tier, "date": _fmt(n.when), "lang": n.lang or "?",
                 "title": n.title, "text": n.body[:500], "role": "origin" if n.id == on.id else "amplifier"}
                for i, n in enumerate(sorted(real, key=lambda n: (n.id != on.id, -descendants(n.id, ch)))[:8])])
            if ai_brief and attribution_ok(ai_brief["text"]):
                brief["narrative"] = ai_brief["text"]
                brief["writer"] = f"{ai_brief['model']} from the facts above; attribution wording checked."
                usd += ai_brief["usage"].get("usd", 0.0)
            elif ai_brief:
                brief["writer"] += " (The model's brief broke the attribution rule and was discarded.)"
        except Exception as e:  # noqa: BLE001
            brief["writer"] += f" (Model brief failed: {ml.explain(e)})"
    if "narrative" not in brief:
        brief["narrative"] = (
            f"This story is about {', '.join(about[:4]) or 'the seed text'}. Its earliest observed source in the "
            f"archive is {on.source} ({_fmt(on.when)}). From there it reached {len(real) - 1} more post(s)"
            + (f", amplified by {', '.join(a['source'] for a in top_amps[:3])}" if top_amps else "")
            + f". The claim is {verdict['verdict'].lower()} and the event scores {tps_r.priority}.")
    yield step("brief", t0, n=10, title="Write the brief", status="ok", summary=headline[:180],
               rows=[["writer", brief["writer"]]],
               explain="What this story is, where it was first seen, who carried it, and what is still unknown, in "
                       "the brief's attribution wording: 'earliest observed source' and 'amplified by', never "
                       "'Serbia/Russia did X'.",
               ai={"state": "used" if ai_brief and "narrative" in brief and ai_brief["text"] == brief["narrative"]
                   else "none", "what": brief["writer"]})

    # result + persistence -----------------------------------------------------------------------------------------
    acceptance = {"root": bool(origin["signal_id"]), "nodes": len(real), "edges": len([b for b in parent
                                                                                        if not byid[b].probe])}
    acceptance["passes"] = acceptance["root"] and acceptance["nodes"] >= 3 and acceptance["edges"] >= 2
    graph_nodes = [{"id": n.id, "source": n.source, "source_id": n.source_id, "tier": n.tier, "platform": n.platform,
                    "lang": n.lang, "when": _iso(n.when), "dated": n.published_at is not None, "title": n.title[:200],
                    "url": n.url, "group": group.get(n.id), "depth": depth[n.id], "probe": n.probe,
                    "reach": descendants(n.id, ch, {x.id: x.source_id for x in nodes}), "origin": n.id == on.id, "seed": n is seed_node,
                    "sim": round(n._cos, 3), "overlap": round(n._ov, 3)} for n in nodes]   # noqa: SLF001
    seed_out = {k: v for k, v in seed.items() if k != "image"} | {"terms": terms}
    if info.get("ocr_text"):
        seed_out |= {"ocr_text": info["ocr_text"], "ocr_engine": info["engine"]}
    if info.get("signal_id"):
        seed_out["signal_id"] = info["signal_id"]
    result = {"type": "result", "seed": seed_out,
              "origin": origin | {"source": on.source, "when": _iso(on.when), "title": on.title, "url": on.url,
                                  "tier": on.tier, "platform": on.platform},
              "seed_path": seed_path, "seed_root": seed_root,
              "graph": {"nodes": graph_nodes, "edges": list(parent.values())},
              "amplifiers": amps[:15], "discovered": discovered,
              "official": [{"id": n.id, "source": n.source, "title": n.title, "when": _iso(n.when), "in_story": True}
                           for n in official] + [{"id": n.id, "source": n.source, "title": n.title,
                                                  "when": _iso(n.when), "in_story": False} for n in near],
              "trigger": trig,
              "significance": {k: {"value": v.value, "normalised": round(v.normalised, 3), "note": v.note}
                               for k, v in sig_feats.items()},
              "tps": {"tps": tps_r.tps, "priority": tps_r.priority, "explanation": tps_r.explanation,
                      "tripwires": trips,
                      "factors": factors, "credibility": tps_r.credibility},
              "verdict": verdict, "brief": brief, "acceptance": acceptance, "usd": round(usd, 6),
              "ms": _ms(t_all), "labels": labels, "narratives": narrs, "steps": log}
    if persist:
        result["event_id"] = save(result, real, parent, group, origin, on, first_t, last_t, discovered, event_id)
    yield result


def save(result: dict, real: list[Node], parent: dict, group: dict, origin: dict, on: Node,
         first_t: datetime | None, last_t: datetime | None, discovered: list[dict], event_id: str | None = None) -> str:
    """Write the trace as an Event (brief Section 9): members with origin groups, typed edges, the origin, scores.
    With event_id, that Event is rewritten in place (its members and edges are replaced)."""
    from sqlalchemy import delete
    eid = event_id or new_id("evt")
    fields = dict(title=(on.title or "Untitled story")[:300], labels=result["labels"] or None,
                  narratives=result["narratives"] or None, first_signal_at=first_t, last_signal_at=last_t,
                  origin={k: origin[k] for k in ("signal_id", "confidence", "method")},
                  scores=result["tps"]["factors"] | {"tps": result["tps"]["tps"],
                                                     "credibility": result["tps"]["credibility"]},
                  significance=result["significance"], priority=result["tps"]["priority"],
                  explanation=result["tps"]["explanation"], verification=result["verdict"],
                  seed=result["seed"], trace={**result, "event_id": eid})
    with session() as s:
        ev = s.get(Event, eid) if event_id else None
        if ev is None:
            s.add(Event(event_id=eid, **fields))
        else:
            s.execute(delete(EventEdge).where(EventEdge.event_id == eid))
            s.execute(delete(EventSignal).where(EventSignal.event_id == eid))
            for k, v in fields.items():
                setattr(ev, k, v)
            ev.updated_at = datetime.now(timezone.utc)
        s.flush()
        for n in real:
            s.add(EventSignal(event_id=eid, signal_id=n.id, origin_group=group.get(n.id)))
        s.flush()
        for b, e in parent.items():
            if e["from"] != PROBE_ID and b != PROBE_ID:
                s.add(EventEdge(event_id=eid, from_signal=e["from"], to_signal=b, type=e["type"],
                                similarity=e["sim"]))
        for d in discovered:
            if d["new"]:
                s.add(DiscoveryQueue(url=d["url"], found_via_signal=d["signal_id"],
                                     reason=f"Tracer {eid}: linked by {d['cited_by']} post(s) in the story"))
    return eid


def load(event_id: str) -> dict | None:
    with session() as s:
        ev = s.get(Event, event_id)
        return ev.trace if ev is not None else None


def recent(limit: int = 12) -> list[dict]:
    with session() as s:
        rows = s.execute(select(Event.event_id, Event.title, Event.priority, Event.created_at, Event.origin,
                                Event.verification, Event.seed).where(Event.trace.is_not(None))
                         .order_by(Event.created_at.desc()).limit(limit)).all()
    return [{"event_id": r[0], "title": r[1], "priority": r[2], "created_at": r[3],
             "confidence": (r[4] or {}).get("confidence"), "verdict": (r[5] or {}).get("verdict"),
             "kind": (r[6] or {}).get("kind")} for r in rows]
