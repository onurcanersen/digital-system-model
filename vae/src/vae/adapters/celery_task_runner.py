"""Celery-backed ITaskRunner: submits and tracks vae's own
vae.worker.run_msd_workflow task."""

from __future__ import annotations

from typing import Dict, Optional

from celery import states
from celery.result import AsyncResult

from vae.domain.task_status import TaskStatus
from vae.ports.task_runner import ITaskRunner
from vae.worker import celery_app, run_msd_workflow


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
        produced_by: Optional[str] = None,
        candidate: Optional[Dict] = None,
    ) -> str:
        async_result = run_msd_workflow.delay(
            project_id, platform_id, version_id,
            config_mgmt_address, config_mgmt_username, config_mgmt_password,
            source_repo_address, source_repo_username, source_repo_password,
            produced_by, candidate,
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
        # A non-terminal task can carry the mid-run state it published itself
        # (update_state's meta — vae's runs use it for the run's progress):
        # the redis backend stores that meta in the same result field the
        # SUCCESS branch reads. Celery's own "started" info (pid/hostname) is
        # not progress, so only a progress-shaped meta is surfaced.
        info = async_result.result
        if not isinstance(info, dict) or "percent" not in info:
            info = None
        return TaskStatus(task_id=task_id, state=state, info=info)

    def cancel(self, task_id: str) -> TaskStatus:
        # terminate=True kills the worker child process if the task is already
        # running (SIGTERM); queued tasks are dropped by the worker on pickup.
        # Fire-and-forget (no reply wait) — the worker marks the task REVOKED
        # in the result backend a moment later.
        AsyncResult(task_id, app=self.app).revoke(terminate=True)
        return self.status(task_id)
