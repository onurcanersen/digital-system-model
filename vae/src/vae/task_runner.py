"""Task-status port + Celery-backed adapter for tracking vae's own Celery
runs (vae.worker.run_msd_workflow). Specific enough to vae's own worker
(one implementation, no swapping in production) to keep as a single module
rather than splitting into msd-style ports/adapters packages."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Optional

from celery import states
from celery.result import AsyncResult

from vae.worker import celery_app, run_msd_workflow


@dataclass
class TaskStatus:
    task_id: str
    state: str  # PENDING | STARTED | SUCCESS | FAILURE | ...
    result: Optional[Dict] = None
    error: Optional[str] = None


class ITaskRunner(ABC):
    @abstractmethod
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
        """Queue one clone → generate execution for a selection, connecting to
        config_mgmt_db and source_code_repo with the given caller-supplied
        credentials. Returns the task id; raises if the execution backend is
        unreachable."""

    @abstractmethod
    def status(self, task_id: str) -> TaskStatus:
        """Current state/result of a submitted execution. Unknown ids report
        as PENDING (the backend cannot distinguish unknown from queued)."""


def _failure_message(result) -> str:
    """Human-readable error for a FAILURE state. Celery hands back the
    reconstructed exception as the result; fall back to its repr, then name."""
    if result is None:
        return "task failed without a stored error"
    message = str(result)
    if message:
        return message
    return repr(result)


class CeleryTaskRunner(ITaskRunner):
    def __init__(self, app=None):
        # Celery resolves the app for AsyncResult from a thread-local
        # current-app, which is unset in Flask request threads and would
        # fall back to an unconfigured default app (disabled backend).
        self.app = app or celery_app

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
        async_result = run_msd_workflow.delay(
            project_id, platform_id, version_id,
            config_mgmt_address, config_mgmt_username, config_mgmt_password,
            source_repo_address, source_repo_username, source_repo_password,
        )
        return async_result.id

    def status(self, task_id: str) -> TaskStatus:
        async_result = AsyncResult(task_id, app=self.app)
        state = async_result.state
        if state == states.FAILURE:
            return TaskStatus(task_id=task_id, state=state, error=_failure_message(async_result.result))
        if state == states.SUCCESS:
            result = async_result.result
            if not isinstance(result, dict):
                result = {"value": result} if result is not None else None
            return TaskStatus(task_id=task_id, state=state, result=result)
        return TaskStatus(task_id=task_id, state=state)
