"""Runtime configuration, read from environment variables."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    cors_origins: tuple[str, ...]


def get_settings() -> Settings:
    return Settings(
        data_dir=Path(os.environ.get("PLATETRAIL_DATA_DIR", Path(__file__).resolve().parents[2] / "data")),
        cors_origins=tuple(
            o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()
        ),
    )
