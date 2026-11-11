"""Runtime configuration, read from environment variables."""

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATABASE_URL = "postgresql+psycopg://platetrail:platetrail@localhost:5434/platetrail"


@dataclass(frozen=True)
class Settings:
    database_url: str
    data_dir: Path
    cors_origins: tuple[str, ...]


def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        data_dir=Path(os.environ.get("PLATETRAIL_DATA_DIR", Path(__file__).resolve().parents[2] / "data")),
        cors_origins=tuple(
            o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()
        ),
    )
