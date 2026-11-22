from alembic import context
from sqlalchemy import create_engine

from parse.models import Base
from parse.settings import DATABASE_URL

target_metadata = Base.metadata


def run_migrations_online() -> None:
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
