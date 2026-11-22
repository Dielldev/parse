"""parse <command>. Thin wrapper over the modules so each step can be run on its own."""
import argparse
import sys


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="parse")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("import-sources", help="load config/sources.csv into the registry")
    sub.add_parser("probe", help="check liveness, robots.txt, feeds and sitemaps of registry sources")
    b = sub.add_parser("backfill", help="historical backfill for the windows in config/windows.yaml")
    b.add_argument("--sources", nargs="*")
    b.add_argument("--windows", nargs="*")
    b.add_argument("--workers", type=int, default=24)
    sub.add_parser("poll", help="one live polling pass over RSS feeds")
    sub.add_parser("coverage", help="write data/coverage_report.md")
    t = sub.add_parser("trace", help="A12 Tracer: trace a signal id, a link or a text back to its earliest source")
    t.add_argument("seed", help="sig_... id, http(s) link, or the text itself")
    t.add_argument("--ai", action="store_true", help="check stance and write the brief with the Qwen models (billed)")
    t.add_argument("--no-save", action="store_true", help="do not store the trace as an Event")
    a = ap.parse_args(argv)

    if a.cmd == "import-sources":
        from parse.db import session
        from parse.registry import import_sources
        with session() as s:
            print(import_sources(s), "sources")
    elif a.cmd == "probe":
        from parse.collectors import probe
        for r in probe.run():
            print("OK " if r["ok"] else "-- ", r["source_id"], r["note"])
    elif a.cmd == "backfill":
        from parse.collectors import backfill
        backfill.run(a.sources, a.windows, a.workers)
    elif a.cmd == "poll":
        from parse.collectors import rss
        print(rss.run())
    elif a.cmd == "coverage":
        from parse import report_coverage
        from parse.settings import DATA_DIR
        t = report_coverage.build()
        (DATA_DIR / "coverage_report.md").write_text(t)
        print(t)
    elif a.cmd == "trace":
        from parse import tracer
        seed = ({"kind": "signal", "signal_id": a.seed} if a.seed.startswith("sig_")
                else {"kind": "url", "url": a.seed} if a.seed.startswith(("http://", "https://"))
                else {"kind": "text", "text": a.seed})
        for ev in tracer.run(seed, ai=a.ai, persist=not a.no_save):
            if ev["type"] == "step":
                print(f"[{ev.get('n', '-')}] {ev['title']}: {ev['summary']}  ({ev['ms']} ms)")
            elif ev["type"] == "error":
                print("!!", ev["message"])
            else:
                b = ev["brief"]
                print("\n" + b["headline"] + "\n\n" + b["narrative"] + "\n")
                for k in b["what_we_know"]:
                    print(" -", k)
                print("\nevent:", ev.get("event_id", "(not saved)"), "·", ev["ms"], "ms")


if __name__ == "__main__":
    sys.exit(main())
