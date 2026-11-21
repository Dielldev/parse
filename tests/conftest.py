import os

import psycopg
import pytest

TEST_DB = "atlas_test"
os.environ["DATABASE_URL"] = f"postgresql+psycopg://atlas:atlas_local_dev@localhost:5433/{TEST_DB}"


def _db_available() -> bool:
    try:
        with psycopg.connect("postgresql://atlas:atlas_local_dev@localhost:5433/atlas", autocommit=True,
                             connect_timeout=3) as c:
            c.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
            c.execute(f"CREATE DATABASE {TEST_DB}")
        return True
    except psycopg.OperationalError:
        return False


@pytest.fixture(scope="session")
def migrated_db():
    if not _db_available():
        pytest.skip("Postgres not running (docker compose up -d)")
    from alembic import command
    from alembic.config import Config

    from atlas.settings import ROOT
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture
def db(migrated_db):
    from atlas.db import SessionLocal
    s = SessionLocal()
    yield s
    s.rollback()
    s.close()
