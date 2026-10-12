import re

from platetrail.db import migration_files


def test_migration_files_are_numbered_and_ordered():
    names = [name for name, _ in migration_files()]
    assert names, "expected at least one migration"
    assert all(re.fullmatch(r"\d{3}_[a-z0-9_]+\.sql", n) for n in names)
    numbers = [int(n[:3]) for n in names]
    assert numbers == sorted(set(numbers)), "migration numbers must be unique and ordered"
