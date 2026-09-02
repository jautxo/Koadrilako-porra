"""Cache en memoria con expiración, para no saturar el límite de peticiones
(10/min en el plan gratuito) de football-data.org cuando varias personas
visitan las páginas de Liga a la vez."""
from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")

_store: dict[str, tuple[float, object]] = {}


def cached(key: str, ttl_seconds: float, fetch: Callable[[], T]) -> T:
    now = time.time()
    entry = _store.get(key)
    if entry is not None and now - entry[0] < ttl_seconds:
        return entry[1]  # type: ignore[return-value]
    value = fetch()
    _store[key] = (now, value)
    return value
