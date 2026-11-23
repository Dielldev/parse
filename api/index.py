"""Vercel entry point: the Parse web demo (read-only snapshot, visitor-supplied model key)."""
import os
import sys
from pathlib import Path

os.environ["PARSE_DEMO"] = "1"   # always, on Vercel: no server-side model key, no writes, no pipeline
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from parse.web.app import app  # noqa: E402,F401
