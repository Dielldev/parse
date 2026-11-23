"""Plain data the Agents page and its public replay share: how each source is read, the scout's destinations,
keyword tags. No network or browser libraries, so the web demo can import it."""
from __future__ import annotations

import re

from sqlalchemy import select

from parse.models import Source
from parse.normalise.text import fold
from parse.settings import keywords

# Plain-language explainer for each way Parse reads a source. `call` is the real request an agent makes.
METHODS = {
    "wp-search": {
        "name": "Site search API", "short": "API",
        "how": "Many news sites run on WordPress, which has a public, read-only search endpoint. The agent asks it "
               "for posts that mention your topic and gets back clean JSON: title, full text and exact time.",
        "call": "GET {site}/wp-json/wp/v2/posts?search=<topic>",
        "speed": "1 request per source", "needs": "Nothing. Public and unauthenticated.",
    },
    "rss": {
        "name": "RSS feed", "short": "RSS",
        "how": "The site's feed lists its newest articles. The agent keeps the ones about Kosovo that match your "
               "topic, then opens each article page to save the full text and publish time.",
        "call": "GET {site}/feed  →  GET <each article>",
        "speed": "1 + 1 per article (2 s apart)", "needs": "Nothing. Public.",
    },
    "sitemap": {
        "name": "Sitemap (history only)", "short": "MAP",
        "how": "Sites without an API or feed publish a sitemap: a list of every URL with a date. Parse used it "
               "for the historical backfill. It is too slow for a live agent, so agents skip these sites.",
        "call": "GET {site}/sitemap.xml",
        "speed": "Backfill only", "needs": "Nothing. Public.",
    },
    "telegram": {
        "name": "Telegram public preview", "short": "TG",
        "how": "Every public channel has a web page at t.me/s/<channel> that shows its latest posts to anyone. "
               "The agent reads that page. No Telegram account, no login, no API key.",
        "call": "GET https://t.me/s/<channel>",
        "speed": "1 request per channel", "needs": "The channel approved in the registry.",
    },
    "discord": {
        "name": "Discord bot", "short": "DC",
        "how": "Discord has no public web pages, so the agent uses Discord's official Bot API with a bot you create. "
               "It can only read channels in servers that invited the bot. Never a personal account (that breaks "
               "Discord's rules).",
        "call": "GET discord.com/api/v10/channels/<id>/messages",
        "speed": "1 request per channel", "needs": "DISCORD_BOT_TOKEN in .env, bot invited to the server.",
    },
}

DESTS = [
    {"kind": "web", "name": "News & official sites", "blurb": "Outlets, ministries, KFOR, EULEX and other sites in the registry."},
    {"kind": "telegram", "name": "Telegram", "blurb": "Public channels, read through their web preview."},
    {"kind": "discord", "name": "Discord", "blurb": "Channels your own bot has been invited to."},
]


# Browser scout destinations, in tab order. `suggest` is filled from the registry.
SCOUT = [
    {"kind": "telegram", "name": "Telegram", "where": "Public channels", "login": False,
     "how": "Pick channels below (or type @names), say what to look for, press the button. The scout opens each "
            "channel's public page, searches it for your words and keeps the posts that match. No account needed.",
     "placeholder": "Pick channels below, or type @channel"},
    {"kind": "discord", "name": "Discord", "where": "Servers you joined", "login": True,
     "how": "Opens the channel in Discord's web app with the agent browser's own account and scrolls back through "
            "the messages. It only sees servers that account joined; joining stays your job.",
     "placeholder": "https://discord.com/channels/…/…"},
    {"kind": "reddit", "name": "Reddit", "where": "Subreddits + threads", "login": False,
     "how": "Searches the subreddit for your topic (or reads its newest posts), then opens the busiest threads and "
            "reads what people say in the comments. Use the visible browser: Reddit blocks hidden ones.",
     "placeholder": "Pick subreddits below, or type r/name (empty = all of Reddit)"},
    {"kind": "x", "name": "X", "where": "Search + profiles", "login": True,
     "how": "Runs an X search for your topic, newest first (or a handle's posts), and scrolls the timeline. "
            "X shows nothing logged out, so log the agent browser in once.", "placeholder": "@handle (empty = all of X)"},
]
SCOUT_SUGGEST = {
    "telegram": [],
    "discord": [],
    "reddit": ["r/kosovo", "r/serbia", "r/albania", "r/balkans_irl"],
    "x": ["@NATO_KFOR", "@KryeministriKS", "@markodjuric"],
}


# One-click topics under "Look for" on every scout tab.
SCOUT_TOPICS = ["Banjska", "Jarinje", "Ibar bridge", "KSF", "Kurti", "mobilisation", "KFOR", "Zvečan"]


TAG_NAMES = {"ksf_military": "KSF / army", "places_north": "North", "police": "Police", "mobilisation": "Mobilisation",
             "violence_sabotage": "Violence", "political": "Political", "war_persecution_framing": "War / persecution",
             "heritage": "Heritage"}


_tags: list[tuple[str, list[str]]] | None = None


def tags_of(text: str) -> list[str]:
    global _tags
    if _tags is None:
        _tags = [(g, sorted({fold(w) for ws in langs.values() for w in ws}))
                 for g, langs in keywords()["topics"].items()]
    blob = fold(text or "")
    out = []
    for g, words in _tags:
        for w in words:
            if (len(w) <= 4 and re.search(rf"\b{re.escape(w)}\b", blob)) or (len(w) > 4 and w in blob):
                out.append(TAG_NAMES.get(g, g))
                break
    return out


def method_of(platform: str, check_note: str | None, feed_urls, sitemap_urls) -> str:
    """The way an agent reads a source (same rule as agents.methods.method_for, without its imports)."""
    if platform in ("discord", "telegram"):
        return platform
    if "wp_api=True" in (check_note or ""):
        return "wp-search"
    if feed_urls:
        return "rss"
    if sitemap_urls:
        return "sitemap"
    return "none"


def suggestions(s, only: set[str] | None = None) -> dict[str, list[str]]:
    out = {k: list(v) for k, v in SCOUT_SUGGEST.items()}   # only: source ids to offer (the replay lists recorded ones)
    for src in s.scalars(select(Source).where(Source.platform.in_(("telegram", "discord", "reddit", "x"))).order_by(Source.tier)):
        if (src.mvp_collect or "").startswith("blocked") or not src.url or (only is not None and src.source_id not in only):
            continue
        tail = src.url.rstrip("/").rsplit("/", 1)[-1]
        label = {"telegram": f"@{tail}", "reddit": f"r/{tail}", "x": f"@{tail}", "discord": src.url}[src.platform]
        if src.source_id.endswith("_search"):
            continue
        if label.lower() not in {x.lower() for x in out[src.platform]}:
            out[src.platform].append(label)
    return {k: v[:10] for k, v in out.items()}
