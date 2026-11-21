"""Spend ledger (data/spend_ledger.csv) and the budget gate for every paid model call.

Provider-neutral. Prices and the cap live in config/models.yaml. When the provider reports the settled
charge (Featherless `usage.cost`) that value is recorded; otherwise the catalog price is used.
"""
from __future__ import annotations

import csv
import threading
from datetime import datetime, timezone
from functools import lru_cache

import yaml

from atlas.settings import CONFIG_DIR, DATA_DIR

LEDGER = DATA_DIR / "spend_ledger.csv"
FIELDS = ["timestamp", "stage", "model", "input_tokens", "output_tokens", "usd", "note"]
_lock = threading.Lock()


class BudgetExceeded(RuntimeError):
    pass


@lru_cache
def models_cfg() -> dict:
    return yaml.safe_load((CONFIG_DIR / "models.yaml").read_text())


def model(role: str) -> dict:
    return models_cfg()["models"][role]


def total_budget() -> float:
    return float(models_cfg()["budget"]["total_usd"])


def cost(role: str, in_tok: int, out_tok: int) -> float:
    m = model(role)
    return (in_tok * m["price_in"] + out_tok * m["price_out"]) / 1e6


def spent() -> float:
    if not LEDGER.exists():
        return 0.0
    return sum(float(r["usd"]) for r in csv.DictReader(LEDGER.open()))


def check(estimate_usd: float) -> None:
    total = spent() + estimate_usd
    if total > total_budget():
        raise BudgetExceeded(f"would reach ${total:.2f}, over the ${total_budget():.2f} budget in config/models.yaml")


def record(stage: str, model_id: str, in_tok: int, out_tok: int, usd: float, note: str = "") -> None:
    with _lock:
        new = not LEDGER.exists()
        with LEDGER.open("a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerow({"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), "stage": stage,
                        "model": model_id, "input_tokens": in_tok, "output_tokens": out_tok,
                        "usd": f"{usd:.6f}", "note": note})
