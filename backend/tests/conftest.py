import os

import pytest

# Tests marked `db` need a PostGIS instance. CI always provides one; locally,
# run `docker compose up -d db` first. Without DATABASE_URL they are skipped.
HAS_DB = bool(os.environ.get("DATABASE_URL"))


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
