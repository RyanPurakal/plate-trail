import pytest
from sqlalchemy import text

from platetrail.db import apply_migrations, migration_files

pytestmark = pytest.mark.db


def test_postgis_available(engine):
    with engine.connect() as conn:
        assert conn.execute(text("SELECT postgis_lib_version()")).scalar_one()


def test_migrations_recorded_and_idempotent(engine):
    assert apply_migrations(engine) == []  # already applied by the fixture
    with engine.connect() as conn:
        recorded = set(conn.execute(text("SELECT name FROM schema_migrations")).scalars())
    assert {name for name, _ in migration_files()} <= recorded
