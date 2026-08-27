"""Synchronous in-memory ITaskRunner for API tests: submit_run executes the
injected workflow callable in-process (no broker) and records the outcome."""

from __future__ import annotations

import uuid
from typing import Callable, Optional

from ports.task_runner import ITaskRunner, TaskStatus


class FakeTaskRunner(ITaskRunner):
    def __init__(self, run: Callable[..., dict]):
        self._run = run
        self._tasks: dict = {}

    def submit_run(self, project_id: str, platform_id: str, version_id: str) -> str:
        task_id = uuid.uuid4().hex
        try:
            result = self._run(task_id=task_id, project_id=project_id,
                               platform_id=platform_id, version_id=version_id)
        except Exception as exc:
            self._tasks[task_id] = TaskStatus(task_id=task_id, state="FAILURE", error=str(exc) or repr(exc))
        else:
            self._tasks[task_id] = TaskStatus(task_id=task_id, state="SUCCESS", result=result)
        return task_id

    def status(self, task_id: str) -> TaskStatus:
        known = self._tasks.get(task_id)
        if known is not None:
            return known
        return TaskStatus(task_id=task_id, state="PENDING")

    def submitted(self) -> list:
        return list(self._tasks)
