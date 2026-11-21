"""atlas <command>. Thin wrapper over the modules so each step can be run on its own."""
import argparse
import sys


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="atlas")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("import-sources", help="load config/sources.csv into the registry")
    sub.add_parser("probe", help="check liveness, robots.txt, feeds and sitemaps of registry sources")
    b = sub.add_parser("backfill", help="historical backfill for the windows in config/windows.yaml")
    b.add_argument("--sources", nargs="*")
    b.add_argument("--windows", nargs="*")
    b.add_argument("--workers", type=int, default=24)
    sub.add_parser("poll", help="one live polling pass over RSS feeds")
    sub.add_parser("coverage", help="write data/coverage_report.md")
    a = ap.parse_args(argv)

    if a.cmd == "import-sources":
        from atlas.db import session
        from atlas.registry import import_sources
        with session() as s:
            print(import_sources(s), "sources")
    elif a.cmd == "probe":
        from atlas.collectors import probe
        for r in probe.run():
            print("OK " if r["ok"] else "-- ", r["source_id"], r["note"])
    elif a.cmd == "backfill":
        from atlas.collectors import backfill
        backfill.run(a.sources, a.windows, a.workers)
    elif a.cmd == "poll":
        from atlas.collectors import rss
        print(rss.run())
    elif a.cmd == "coverage":
        from atlas import report_coverage
        from atlas.settings import DATA_DIR
        t = report_coverage.build()
        (DATA_DIR / "coverage_report.md").write_text(t)
        print(t)


if __name__ == "__main__":
    sys.exit(main())
