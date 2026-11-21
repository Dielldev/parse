"""Database tables. Signal, Event and Alert follow brief Section 9 field-for-field."""
from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

PLATFORMS = ("telegram", "x", "facebook", "tiktok", "youtube", "news", "mirror", "official", "restricted", "reddit")
EDGE_TYPES = ("forward", "quote", "copy", "link", "translate")
EMBED_DIM = 1024  # Qwen/Qwen3-Embedding-0.6B (config/models.yaml)


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
    feed_urls: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    sitemap_urls: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Signal(Base):
    __tablename__ = "signal"
    signal_id: Mapped[str] = mapped_column(String, primary_key=True)
    platform: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[str] = mapped_column(ForeignKey("source.source_id"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    author_handle: Mapped[str | None] = mapped_column(Text)
    author_followers: Mapped[int | None] = mapped_column(BigInteger)
    author_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lang: Mapped[str | None] = mapped_column(String, index=True)
    title: Mapped[str | None] = mapped_column(Text)
    text_original: Mapped[str | None] = mapped_column(Text)
    text_latin: Mapped[str | None] = mapped_column(Text)  # Serbian Cyrillic transliterated to Latin
    text_en: Mapped[str | None] = mapped_column(Text)
    media: Mapped[list | None] = mapped_column(JSONB)
    forwarded_from: Mapped[str | None] = mapped_column(String)
    links_out: Mapped[list | None] = mapped_column(JSONB)
    engagement: Mapped[dict | None] = mapped_column(JSONB)
    labels: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    narratives: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    entities: Mapped[dict | None] = mapped_column(JSONB)
    evidence_sha256: Mapped[str | None] = mapped_column(ForeignKey("evidence.sha256"))
    collector: Mapped[dict | None] = mapped_column(JSONB)
    legal_basis: Mapped[str] = mapped_column(String, nullable=False, server_default="public")
    window: Mapped[str | None] = mapped_column(String, index=True)  # backfill window tag
    embedding = mapped_column(Vector(EMBED_DIM), nullable=True)
    __table_args__ = (
        UniqueConstraint("source_id", "url", name="uq_signal_source_url"),
        CheckConstraint(f"platform IN {PLATFORMS}", name="ck_signal_platform"),
        CheckConstraint("legal_basis = 'public' OR legal_basis LIKE 'restricted:_%'", name="ck_signal_legal_basis"),
    )


class Event(Base):
    __tablename__ = "event"
    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str | None] = mapped_column(Text)
    labels: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    narratives: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    first_signal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_signal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin: Mapped[dict | None] = mapped_column(JSONB)
    scores: Mapped[dict | None] = mapped_column(JSONB)
    significance: Mapped[dict | None] = mapped_column(JSONB)  # features + plain-language explanations
    tripwires: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    priority: Mapped[str | None] = mapped_column(String)
    explanation: Mapped[str | None] = mapped_column(Text)
    verification: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    brief: Mapped[str | None] = mapped_column(Text)
    what_we_know: Mapped[list | None] = mapped_column(JSONB)
    what_we_dont_know: Mapped[list | None] = mapped_column(JSONB)
    suggested_checks: Mapped[list | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String, server_default="new")
    analyst_id: Mapped[str | None] = mapped_column(String)
    feedback: Mapped[dict | None] = mapped_column(JSONB)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LlmOutput(Base):
    """Every LLM call's output, stored with its prompt version and cost."""
    __tablename__ = "llm_output"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stage: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String, nullable=False)
    subject_id: Mapped[str | None] = mapped_column(String, index=True)
    output: Mapped[dict | None] = mapped_column(JSONB)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    usd: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    """Write-once: the migration installs a trigger that rejects UPDATE and DELETE."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSONB)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
