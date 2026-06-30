"""In-process LRU cache for expensive pipeline runs used by live previews."""
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
        now = time.monotonic()
        with self._lock:
            fresh = self._get_fresh(key, now)
            if fresh is not None:
                self.hits += 1
                cfg, result = fresh
                return cfg, result
            if key in self._inflight:
                event = self._inflight[key]
                leader = False
            else:
                event = Event()
                self._inflight[key] = event
                leader = True

        if not leader:
            event.wait(timeout=300.0)
            with self._lock:
                fresh = self._get_fresh(key, time.monotonic())
                if fresh is not None:
                    self.hits += 1
                    return fresh
            # Leader failed or entry expired — fall through as new leader.

        try:
            cfg = validate(data)
            result = pipeline_run(cfg)
        except Exception:
            with self._lock:
                inflight = self._inflight.pop(key, None)
            if inflight is not None:
                inflight.set()
            raise

        with self._lock:
            self.misses += 1
            if len(self._entries) >= self._max_entries:
                oldest_key = min(self._entries.items(), key=lambda item: item[1][0])[0]
                del self._entries[oldest_key]
            self._entries[key] = (now, cfg, result)
            inflight = self._inflight.pop(key, None)
        if inflight is not None:
            inflight.set()
        return cfg, result

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
