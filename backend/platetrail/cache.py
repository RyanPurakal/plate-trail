"""Small key-value cache: Redis when REDIS_URL is set, otherwise in-process memory.

Used for the route cache (routing.Router) and the run cache (jobs). Values
are pickled. Both backends are best-effort: a cache failure never fails the
computation, it just recomputes.
"""

import os
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


class RedisCache:
    def __init__(self, url: str, prefix: str = "platetrail:"):
        import redis

        self.r = redis.Redis.from_url(url)
        self.prefix = prefix

    def get(self, key: str) -> Any:
        try:
            raw = self.r.get(self.prefix + key)
        except Exception:  # noqa: BLE001 - cache is best-effort
            return MISSING
        return MISSING if raw is None else pickle.loads(raw)

    def set(self, key: str, value: Any, ttl_s: int | None = None) -> None:
        try:
            self.r.set(self.prefix + key, pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL), ex=ttl_s)
        except Exception:  # noqa: BLE001
            pass


_cache: Cache | None = None


def get_cache() -> Cache:
    global _cache
    if _cache is None:
        url = os.environ.get("REDIS_URL")
        _cache = RedisCache(url) if url else MemoryCache()
    return _cache


def reset_cache(cache: Cache | None = None) -> None:
    """For tests: replace (or clear) the process-wide cache."""
    global _cache
    _cache = cache
