"""Disk cache for raw source responses, keyed by a hash of the request."""

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


class RawCache:
    def __init__(self, directory: Path):
        self.directory = directory

    def path_for(self, request_key: str) -> Path:
        digest = hashlib.sha256(request_key.encode()).hexdigest()[:16]
        return self.directory / f"{digest}.json"

    def fetched_at(self, request_key: str) -> datetime | None:
        """When the cached response for this request was fetched, or None if not cached."""
        path = self.path_for(request_key)
        if not path.exists():
            return None
        return datetime.fromisoformat(json.loads(path.read_text())["fetched_at"])

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
        # write then rename, so a reader never sees a half-written file
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(envelope))
        os.replace(tmp, path)
        return response
