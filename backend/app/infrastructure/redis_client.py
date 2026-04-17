"""Redis client utilities for LAB 05."""

import os
from functools import lru_cache
from typing import Any

try:
    from redis.asyncio import Redis
except ModuleNotFoundError:  # pragma: no cover - fallback for minimal test envs.
    Redis = None  # type: ignore[assignment]


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


@lru_cache
def get_redis() -> Any:
    """
    Получить singleton-клиент Redis.

    TODO (опционально):
    - добавить retry policy / timeouts
    - добавить namespace/prefix
    """
    if Redis is None:
        raise RuntimeError("redis package is not installed")
    return Redis.from_url(REDIS_URL, decode_responses=True)
