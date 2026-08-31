"""Redis-backed store of a task's output lines: one list per task
(``<key_prefix><task_id>``), appended by the worker while the task runs and
streamed back by the API. Lines expire with the task's result (same TTL as
Celery's result_expires), so no output outlives the run it belongs to."""

from __future__ import annotations

from typing import List

import redis

from vae.ports.task_output_store import ITaskOutputStore


class RedisTaskOutputStore(ITaskOutputStore):
    def __init__(self, url: str, key_prefix: str = "dsm:task-output:", ttl: int = 86400):
        self._client = redis.Redis.from_url(url, decode_responses=True)
        self._key_prefix = key_prefix
        self._ttl = ttl

    def _key(self, task_id: str) -> str:
        return f"{self._key_prefix}{task_id}"

    def append(self, task_id: str, line: str) -> None:
        # Raises on store failure; the caller owns the "never fail the task
        # over a dead output channel" policy (the worker's handler catches).
        self._client.rpush(self._key(task_id), line)
        self._client.expire(self._key(task_id), self._ttl)

    def lines(self, task_id: str) -> List[str]:
        return self._client.lrange(self._key(task_id), 0, -1)
