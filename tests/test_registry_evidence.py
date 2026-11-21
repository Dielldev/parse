import os

import pytest
from sqlalchemy import select, text

from atlas.evidence import archive, verify
from atlas.models import AuditLog, Evidence, Source
from atlas.registry import RegistryGateError, gate, import_sources, match_source


def test_import_has_100_plus_sources_with_valid_tiers(db):
    n = import_sources(db)
    db.flush()
    assert n >= 100
    tiers = {t for (t,) in db.execute(select(Source.tier))}
    assert tiers <= {0, 1, 2, 3}
    # Every Tier-0 source carries a scope (own actions only).
    missing = db.scalars(select(Source).where(Source.tier == 0, Source.tier0_scope.is_(None))).all()
    assert missing == []
    # Telegram is deferred by decision on 2026-11-21.
    assert {s.mvp_collect for s in db.scalars(select(Source).where(Source.platform == "telegram"))} == {"later"}


def test_match_source_longest_prefix():
    a = Source(source_id="a", url="https://www.example.com/", name="a", platform="news", tier=1,
               status="verified", mvp_collect="yes")
    b = Source(source_id="b", url="https://example.com/en", name="b", platform="news", tier=1,
               status="verified", mvp_collect="yes")
    assert match_source([a, b], "https://example.com/en/news/1").source_id == "b"
    assert match_source([a, b], "https://example.com/sq/lajme/1").source_id == "a"
    assert match_source([a, b], "https://other.org/x") is None


def test_gate_blocks_unregistered_unverified_and_deferred(db):
    import_sources(db)
    db.flush()
    with pytest.raises(RegistryGateError, match="not in registry"):
        gate(db, "https://random-unknown-site.example/post", "test")
    with pytest.raises(RegistryGateError, match="to-verify"):
        gate(db, "https://www.koha.net/arberi/1", "test")  # registered but not yet verified
    with pytest.raises(RegistryGateError, match="phase2"):
        gate(db, "https://x.com/bellingcat/status/1", "test")  # X is Phase 2
    assert gate(db, "https://telegrafi.com/lajm/1", "test").source_id == "src_web_telegrafi"
    allowed = [a.allowed for a in db.scalars(select(AuditLog).where(AuditLog.actor == "test"))]
    assert allowed.count(False) == 3 and allowed.count(True) == 1


def test_evidence_is_hashed_and_write_once(db, tmp_path):
    sha = archive(db, "https://telegrafi.com/x", b"<html>hi</html>", "hi", "text/html", base=tmp_path)
    f = next(tmp_path.rglob(f"{sha}.html"))
    assert verify(f, sha)
    assert not os.access(f, os.W_OK)  # read-only on disk
    assert archive(db, "https://telegrafi.com/x", b"<html>hi</html>", "hi", base=tmp_path) == sha  # idempotent
    assert db.get(Evidence, sha) is not None
    db.commit()
    with pytest.raises(Exception, match="write-once"):
        db.execute(text("DELETE FROM evidence WHERE sha256 = :s"), {"s": sha})
    db.rollback()


def test_audit_log_is_write_once(db):
    db.add(AuditLog(actor="t", action="x", allowed=True))
    db.commit()
    with pytest.raises(Exception, match="write-once"):
        db.execute(text("UPDATE audit_log SET actor = 'y'"))
    db.rollback()


def test_signal_legal_basis_constraint(db):
    with pytest.raises(Exception, match="ck_signal_legal_basis"):
        db.execute(text("INSERT INTO source (source_id, platform, name, tier, status, mvp_collect) "
                        "VALUES ('src_t','news','t',1,'verified','yes')"))
        db.execute(text("INSERT INTO signal (signal_id, platform, source_id, url, legal_basis) "
                        "VALUES ('sig_t','news','src_t','u','restricted:')"))
    db.rollback()
