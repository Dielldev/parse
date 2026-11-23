"""Database tables. Signal, Event and Alert follow brief Section 9 field-for-field."""
from __future__ import annotations

from datetime import datetime

from datetime import timezone

from sqlalchemy import (
    JSON, BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text,
    TypeDecorator, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

try:   # pgvector is only needed against Postgres; the read-only web demo (SQLite) runs without it
    from pgvector.sqlalchemy import Vector
except ImportError:  # pragma: no cover
    Vector = None

PLATFORMS = ("telegram", "x", "facebook", "tiktok", "youtube", "news", "mirror", "official", "restricted", "reddit",
             "discord")
EDGE_TYPES = ("forward", "quote", "copy", "link", "translate")
EMBED_DIM = 1024  # Qwen/Qwen3-Embedding-0.6B (config/models.yaml)


# Portable column types. Postgres keeps its native types; the SQLite snapshot used by the web demo stores the same
# values as JSON text, and gets timezone-aware datetimes back (SQLite drops the zone).
JSONType = JSON().with_variant(JSONB(), "postgresql")
StrArray = JSON().with_variant(ARRAY(String), "postgresql")
TextArray = JSON().with_variant(ARRAY(Text), "postgresql")
VectorType = (Vector(EMBED_DIM) if Vector is not None else LargeBinary()).with_variant(LargeBinary(), "sqlite")


class TZDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None and dialect.name == "sqlite":
            return value.astimezone(timezone.utc)   # SQLite keeps no zone: store everything as UTC
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "source"
    source_id: Mapped[str] = mapped_column(String, primary_key=True)
    platform: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    lang: Mapped[str | None] = mapped_column(String)
    # 0 official/primary, 1 established outlet, 2 specialist OSINT, 3 partisan or unverified
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    bias_note: Mapped[str | None] = mapped_column(Text)
    # Tier 0 counts as Tier 0 only for claims inside this scope (the institution's own actions).
    tier0_scope: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, nullable=False)  # verified | to-verify | seed | ...
    mvp_collect: Mapped[str] = mapped_column(String, nullable=False)  # yes | phase2 | later | blocked:*
    origin: Mapped[str | None] = mapped_column(String)
    feed_urls: Mapped[list[str] | None] = mapped_column(TextArray)
    sitemap_urls: Mapped[list[str] | None] = mapped_column(TextArray)
    last_checked_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    check_note: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("tier BETWEEN 0 AND 3", name="ck_source_tier"),
        CheckConstraint(f"platform IN {PLATFORMS}", name="ck_source_platform"),
    )


class Evidence(Base):
    """Archived raw page/post. Files are content-addressed and written once."""
    __tablename__ = "evidence"
    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    html_uri: Mapped[str] = mapped_column(Text, nullable=False)
    text_uri: Mapped[str | None] = mapped_column(Text)
    screenshot_uri: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(String)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    fetched_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())


class Signal(Base):
    __tablename__ = "signal"
    signal_id: Mapped[str] = mapped_column(String, primary_key=True)
    platform: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[str] = mapped_column(ForeignKey("source.source_id"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    author_handle: Mapped[str | None] = mapped_column(Text)
    author_followers: Mapped[int | None] = mapped_column(BigInteger)
    author_created_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    published_at: Mapped[datetime | None] = mapped_column(TZDateTime(), index=True)
    first_seen_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
    lang: Mapped[str | None] = mapped_column(String, index=True)
    title: Mapped[str | None] = mapped_column(Text)
    text_original: Mapped[str | None] = mapped_column(Text)
    text_latin: Mapped[str | None] = mapped_column(Text)  # Serbian Cyrillic transliterated to Latin
    text_en: Mapped[str | None] = mapped_column(Text)
    media: Mapped[list | None] = mapped_column(JSONType)
    forwarded_from: Mapped[str | None] = mapped_column(String)
    links_out: Mapped[list | None] = mapped_column(JSONType)
    engagement: Mapped[dict | None] = mapped_column(JSONType)
    labels: Mapped[list[str] | None] = mapped_column(StrArray)
    narratives: Mapped[list[str] | None] = mapped_column(StrArray)
    entities: Mapped[dict | None] = mapped_column(JSONType)
    evidence_sha256: Mapped[str | None] = mapped_column(ForeignKey("evidence.sha256"))
    collector: Mapped[dict | None] = mapped_column(JSONType)
    legal_basis: Mapped[str] = mapped_column(String, nullable=False, server_default="public")
    window: Mapped[str | None] = mapped_column(String, index=True)  # backfill window tag
    embedding = mapped_column(VectorType, nullable=True)
    __table_args__ = (
        UniqueConstraint("source_id", "url", name="uq_signal_source_url"),
        CheckConstraint(f"platform IN {PLATFORMS}", name="ck_signal_platform"),
        CheckConstraint("legal_basis = 'public' OR legal_basis LIKE 'restricted:_%'", name="ck_signal_legal_basis"),
    )


class Event(Base):
    __tablename__ = "event"
    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str | None] = mapped_column(Text)
    labels: Mapped[list[str] | None] = mapped_column(StrArray)
    narratives: Mapped[list[str] | None] = mapped_column(StrArray)
    first_signal_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    last_signal_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    origin: Mapped[dict | None] = mapped_column(JSONType)
    scores: Mapped[dict | None] = mapped_column(JSONType)
    significance: Mapped[dict | None] = mapped_column(JSONType)  # features + plain-language explanations
    tripwires: Mapped[list[str] | None] = mapped_column(StrArray)
    priority: Mapped[str | None] = mapped_column(String)
    explanation: Mapped[str | None] = mapped_column(Text)
    verification: Mapped[dict | None] = mapped_column(JSONType)
    seed: Mapped[dict | None] = mapped_column(JSONType)   # what the Tracer started from (signal, text, image, URL)
    trace: Mapped[dict | None] = mapped_column(JSONType)  # the Tracer's full result, as shown on /trace/<event_id>
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())


class EventSignal(Base):
    __tablename__ = "event_signal"
    event_id: Mapped[str] = mapped_column(ForeignKey("event.event_id", ondelete="CASCADE"), primary_key=True)
    signal_id: Mapped[str] = mapped_column(ForeignKey("signal.signal_id"), primary_key=True)
    origin_group: Mapped[str | None] = mapped_column(String)


class EventEdge(Base):
    __tablename__ = "event_edge"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("event.event_id", ondelete="CASCADE"), index=True)
    from_signal: Mapped[str] = mapped_column(ForeignKey("signal.signal_id"))
    to_signal: Mapped[str] = mapped_column(ForeignKey("signal.signal_id"))
    type: Mapped[str] = mapped_column(String, nullable=False)
    similarity: Mapped[float | None] = mapped_column(Float)
    __table_args__ = (CheckConstraint(f"type IN {EDGE_TYPES}", name="ck_edge_type"),)


class Alert(Base):
    __tablename__ = "alert"
    alert_id: Mapped[str] = mapped_column(String, primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("event.event_id"), index=True)
    priority: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
    brief: Mapped[str | None] = mapped_column(Text)
    what_we_know: Mapped[list | None] = mapped_column(JSONType)
    what_we_dont_know: Mapped[list | None] = mapped_column(JSONType)
    suggested_checks: Mapped[list | None] = mapped_column(JSONType)
    status: Mapped[str] = mapped_column(String, server_default="new")
    analyst_id: Mapped[str | None] = mapped_column(String)
    feedback: Mapped[dict | None] = mapped_column(JSONType)
    __table_args__ = (
        CheckConstraint("status IN ('new','triaged','escalated','dismissed')", name="ck_alert_status"),
        CheckConstraint("priority IN ('P1','P2','P3','P4')", name="ck_alert_priority"),
    )


class DiscoveryQueue(Base):
    """Unknown upstream sources found by collectors/tracer. A human approves before any collection."""
    __tablename__ = "discovery_queue"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(Text, unique=True)
    found_via_signal: Mapped[str | None] = mapped_column(String)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, server_default="pending")
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())


class LlmOutput(Base):
    """Every LLM call's output, stored with its prompt version and cost."""
    __tablename__ = "llm_output"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stage: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String, nullable=False)
    subject_id: Mapped[str | None] = mapped_column(String, index=True)
    output: Mapped[dict | None] = mapped_column(JSONType)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    usd: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())


class AuditLog(Base):
    """Write-once: the migration installs a trigger that rejects UPDATE and DELETE."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
    actor: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSONType)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)


class AgentRun(Base):
    """One dispatch from the Agents page or Ask Parse: which sources an agent visited and what it kept."""
    __tablename__ = "agent_run"
    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # web | telegram | discord
    topic: Mapped[str | None] = mapped_column(Text)
    source_ids: Mapped[list[str] | None] = mapped_column(StrArray)
    status: Mapped[str] = mapped_column(String, nullable=False)  # running | done | failed
    origin: Mapped[str] = mapped_column(String, nullable=False, server_default="agents-page")
    stats: Mapped[dict | None] = mapped_column(JSONType)       # per-source outcome
    signal_ids: Mapped[list[str] | None] = mapped_column(StrArray)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime())
