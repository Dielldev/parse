"""Runtime settings, loaded from the environment and the versioned YAML config files."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

# Web demo (Vercel): read-only SQLite snapshot, no pipeline, no server-side model key. Visitors bring their own key.
DEMO = os.environ.get("PARSE_DEMO") == "1"
DEMO_DB = ROOT / "demo" / "parse_demo.sqlite"
DEMO_DB_GZ = ROOT / "demo" / "parse_demo.sqlite.gz"

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://atlas:atlas_local_dev@localhost:5433/atlas")
USER_AGENT = os.environ.get("PARSE_USER_AGENT", "ParseResearchBot/0.1 (OSINT research; respects robots.txt)")
EVIDENCE_DIR = ROOT / os.environ.get("EVIDENCE_DIR", "data/evidence")


@lru_cache
def keywords() -> dict:
    return yaml.safe_load((CONFIG_DIR / "keywords.yaml").read_text())


@lru_cache
def thresholds() -> dict:
    return yaml.safe_load((CONFIG_DIR / "thresholds.yaml").read_text())
