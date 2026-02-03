from __future__ import annotations

import redis.asyncio as redis

QUEUE_KEY = "adaspeas:jobs"


async def get_redis(url: str) -> redis.Redis:
    return redis.from_url(url, decode_responses=True)


async def enqueue(r: redis.Redis, job_id: int) -> None:
    await r.rpush(QUEUE_KEY, str(job_id))


async def dequeue(r: redis.Redis, timeout_s: int = 5) -> int | None:
    # BLPOP returns (key, value) or None
    res = await r.blpop(QUEUE_KEY, timeout=timeout_s)
    if not res:
        return None
    _, value = res
    return int(value)
