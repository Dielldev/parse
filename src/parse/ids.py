"""Prefixed ULIDs, as in the brief's schemas (sig_01J..., evt_01J..., alr_01J...)."""
from datetime import datetime

from ulid import ULID


def new_id(prefix: str, at: datetime | None = None) -> str:
    u = ULID.from_datetime(at) if at else ULID()
    return f"{prefix}_{u}"
