"""Disk cache for raw source responses, keyed by a hash of the request."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


class RawCache:
    def __init__(self, directory: Path):
        self.directory = directory

    def path_for(self, request_key: str) -> Path:
        digest = hashlib.sha256(request_key.encode()).hexdigest()[:16]
        return self.directory / f"{digest}.json"

    def get_or_fetch(self, request_key: str, fetch: Callable[[], Any], refresh: bool = False) -> Any:
        path = self.path_for(request_key)
        if path.exists() and not refresh:
            return json.loads(path.read_text())["response"]
        response = fetch()
        self.directory.mkdir(parents=True, exist_ok=True)
        envelope = {
            "request": request_key,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "response": response,
        }
        path.write_text(json.dumps(envelope))
        return response
