"""Small query helpers that read the same on Postgres (pipeline) and SQLite (read-only web demo)."""
from __future__ import annotations

from sqlalchemy import Integer, cast, func, literal
from sqlalchemy.sql.elements import ColumnElement

from parse.settings import DEMO


def blob(*cols) -> ColumnElement:
    """The columns joined with spaces into one searchable string (NULLs skipped)."""
    out = None
    for c in cols:
        part = func.coalesce(c, "")
        out = part if out is None else out + literal(" ") + part
    return out


def regex_match(col: ColumnElement, pattern: str) -> ColumnElement:
    """Case-insensitive regex match of `pattern` against `col`."""
    if DEMO:
        return func.parse_regex(pattern, col) == 1
    return col.op("~*")(pattern)


def regex_hit(col: ColumnElement, pattern: str) -> ColumnElement:
    """1 when the pattern matches else 0, so hits can be summed."""
    if DEMO:
        return func.parse_regex(pattern, col)
    return cast(col.op("~*")(pattern), Integer)


def seconds_apart(col: ColumnElement, ref) -> ColumnElement:
    """Absolute distance in seconds between a timestamp column and a Python datetime."""
    if DEMO:
        return func.abs(func.julianday(col) - func.julianday(ref)) * 86400.0
    return func.abs(func.extract("epoch", col - ref))
