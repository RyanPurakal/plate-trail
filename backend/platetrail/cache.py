"""Small in-process key-value cache, used for the route cache (routing.Router).

Values are pickled. It is best-effort: a cache miss just recomputes.
"""

import pickle
from collections import OrderedDict
from threading import Lock
from typing import Any, Protocol

MISSING = object()


class Cache(Protocol):
    def get(self, key: str) -> Any: ...  # returns MISSING when absent

    def set(self, key: str, value: Any, ttl_s: int | None = None) -> None: ...


class MemoryCache:
    def __init__(self, max_items: int = 50_000):
        self.max_items = max_items
        self._d: OrderedDict[str, bytes] = OrderedDict()
        self._lock = Lock()

    def get(self, key: str) -> Any:
        with self._lock:
            raw = self._d.get(key)
            if raw is None:
                return MISSING
            self._d.move_to_end(key)
        return pickle.loads(raw)

    def set(self, key: str, value: Any, ttl_s: int | None = None) -> None:
        raw = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        with self._lock:
            self._d[key] = raw
            self._d.move_to_end(key)
            while len(self._d) > self.max_items:
                self._d.popitem(last=False)


_cache: Cache | None = None


def get_cache() -> Cache:
    global _cache
    if _cache is None:
        _cache = MemoryCache()
    return _cache


def reset_cache(cache: Cache | None = None) -> None:
    """For tests: replace (or clear) the process-wide cache."""
    global _cache
    _cache = cache
