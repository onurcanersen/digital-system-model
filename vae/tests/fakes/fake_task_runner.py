"""Synchronous in-memory ITaskRunner for vae's API tests: submit_run
executes the injected callable in-process (no broker) and records the
outcome, mirroring msd's own FakeTaskRunner."""

from __future__ import annotations

import uuid
from typing import Callable

from vae.task_runner import ITaskRunner, TaskStatus


class FakeTaskRunner(ITaskRunner):
    def __init__(self, run: Callable[..., dict]):
        self._run = run
        self._tasks: dict = {}

    def submit_run(
        self,
        project_id: str,
        platform_id: str,
        version_id: str,
        config_mgmt_address: str,
        config_mgmt_username: str,
        config_mgmt_password: str,
        source_repo_address: str,
        source_repo_username: str,
        source_repo_password: str,
    ) -> str:
        task_id = uuid.uuid4().hex
        try:
            result = self._run(
                project_id=project_id,
                platform_id=platform_id,
                version_id=version_id,
                config_mgmt_address=config_mgmt_address,
                config_mgmt_username=config_mgmt_username,
                config_mgmt_password=config_mgmt_password,
                source_repo_address=source_repo_address,
                source_repo_username=source_repo_username,
                source_repo_password=source_repo_password,
            )
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
