import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

# Tests marked `db` need a PostGIS instance. CI always provides one; locally,
# run `docker compose up -d db` first. Without DATABASE_URL they are skipped.
#
# Tests never touch the database named in DATABASE_URL: they use a sibling
# database with a `_test` suffix, created on demand, because ETL tests
# truncate tables and would otherwise wipe real camera data.
HAS_DB = bool(os.environ.get("DATABASE_URL"))


def _use_test_database() -> None:
    url = make_url(os.environ["DATABASE_URL"])
    if url.database.endswith("_test"):
        return
    test_url = url.set(database=f"{url.database}_test")
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": test_url.database}).first()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{test_url.database}"'))
    admin.dispose()
    os.environ["DATABASE_URL"] = test_url.render_as_string(hide_password=False)


if HAS_DB:
    _use_test_database()


def pytest_collection_modifyitems(config, items):
    if HAS_DB:
        return
    skip = pytest.mark.skip(reason="DATABASE_URL not set; start PostGIS to run db tests")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def engine():
    from platetrail.db import apply_migrations, get_engine

    eng = get_engine()
    apply_migrations(eng)
    return eng
