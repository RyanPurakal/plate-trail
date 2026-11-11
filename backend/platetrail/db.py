"""Database engine and a minimal ordered-SQL migration runner.

Migrations are plain SQL files in platetrail/sql named NNN_description.sql.
Each is applied once, in order, and recorded in schema_migrations. This keeps
the schema identical across docker-compose, CI, and local runs without
depending on Postgres init scripts.
"""

from functools import lru_cache
from importlib import resources

from sqlalchemy import Engine, create_engine, text

from platetrail.config import get_settings


@lru_cache(maxsize=None)
def get_engine(url: str | None = None) -> Engine:
    return create_engine(url or get_settings().database_url, pool_pre_ping=True)


def migration_files() -> list[tuple[str, str]]:
    sql_dir = resources.files("platetrail") / "sql"
    files = sorted(p for p in sql_dir.iterdir() if p.name.endswith(".sql"))
    return [(p.name, p.read_text()) for p in files]


def apply_migrations(engine: Engine) -> list[str]:
    """Apply pending migrations; return the names of those applied this call."""
    applied_now: list[str] = []
    with engine.begin() as conn:
        # Serialize concurrent callers (e.g. API workers starting together).
        conn.execute(text("SELECT pg_advisory_xact_lock(727274)"))
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " name text PRIMARY KEY,"
                " applied_at timestamptz NOT NULL DEFAULT now())"
            )
        )
        done = set(conn.execute(text("SELECT name FROM schema_migrations")).scalars())
        for name, sql in migration_files():
            if name in done:
                continue
            conn.exec_driver_sql(sql)
            conn.execute(text("INSERT INTO schema_migrations (name) VALUES (:n)"), {"n": name})
            applied_now.append(name)
    return applied_now


if __name__ == "__main__":
    names = apply_migrations(get_engine())
    print(f"Applied {len(names)} migration(s): {', '.join(names) or 'none pending'}")
