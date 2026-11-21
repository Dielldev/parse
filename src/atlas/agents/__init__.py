"""Field agents: send a collector to chosen registry sources, watch it work, keep what it finds.

An agent run is one dispatch. It visits each chosen source with the method that source supports, keeps new
items as Signals (through the same evidence store and registry gate as the backfill) and records what
happened per source, so the Agents page and Ask Atlas can show it.

Methods, in plain words:
  wp-search  WordPress sites answer /wp-json/wp/v2/posts?search=<topic>: a public, read-only search API.
  rss        The site's RSS feed lists its newest articles; the agent keeps those that match the topic.
  telegram   Public channels have a web preview at t.me/s/<channel>; no account and no login.
  discord    Discord's Bot API, with a bot you created and that a server admin invited to the channel.
"""
