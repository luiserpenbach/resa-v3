"""In-process TTL cache (oldest-entry eviction) for live-preview pipeline runs."""
from __future__ import annotations

import hashlib
import json
import time
from threading import Event, Lock
from typing import Any

from resa.config.schema import EngineConfig
from resa.pipeline import run as pipeline_run


class PipelinePreviewCache:
    """Cache ``pipeline_run`` results keyed by full config dict hash."""

    def __init__(self, *, max_entries: int = 48, ttl_s: float = 120.0) -> None:
        self._max_entries = max_entries
        self._ttl_s = ttl_s
        self._entries: dict[str, tuple[float, EngineConfig, Any]] = {}
        self._inflight: dict[str, Event] = {}
        self._lock = Lock()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def config_key(data: dict[str, Any]) -> str:
        payload = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()

    def _get_fresh(self, key: str, now: float) -> tuple[EngineConfig, Any] | None:
        hit = self._entries.get(key)
        if hit is None:
            return None
        ts, cfg, result = hit
        if now - ts >= self._ttl_s:
            del self._entries[key]
            return None
        return cfg, result

    def get_or_run(self, data: dict[str, Any], validate) -> tuple[EngineConfig, Any]:
        key = self.config_key(data)
        while True:
            with self._lock:
                fresh = self._get_fresh(key, time.monotonic())
                if fresh is not None:
                    self.hits += 1
                    return fresh
                event = self._inflight.get(key)
                if event is None:
                    # We are the leader for this key.
                    event = Event()
                    self._inflight[key] = event
                    break
            # Follower: wait for the leader, then re-contend — exactly one
            # waker becomes the new leader if the entry is missing (leader
            # failed), instead of every waiter re-running the pipeline.
            if not event.wait(timeout=300.0):
                with self._lock:
                    # Leader looks stuck; clear its slot (identity-checked so
                    # a finished leader's cleanup is never clobbered) and
                    # re-contend for leadership.
                    if self._inflight.get(key) is event:
                        del self._inflight[key]

        try:
            cfg = validate(data)
            result = pipeline_run(cfg)
        except Exception:
            self._release(key, event)
            raise

        with self._lock:
            self.misses += 1
            if len(self._entries) >= self._max_entries:
                oldest_key = min(self._entries.items(), key=lambda item: item[1][0])[0]
                del self._entries[oldest_key]
            # Timestamp at store time: an entry produced by a pipeline slower
            # than the TTL must still be fresh for the waiters it unblocks.
            self._entries[key] = (time.monotonic(), cfg, result)
        self._release(key, event)
        return cfg, result

    def _release(self, key: str, event: Event) -> None:
        """Drop our in-flight slot (identity-checked) and wake waiters."""
        with self._lock:
            if self._inflight.get(key) is event:
                del self._inflight[key]
        event.set()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "entries": len(self._entries),
                "hits": self.hits,
                "misses": self.misses,
                "max_entries": self._max_entries,
                "ttl_s": self._ttl_s,
            }

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


# Shared cache for the studio preview API process.
PIPELINE_CACHE = PipelinePreviewCache()
