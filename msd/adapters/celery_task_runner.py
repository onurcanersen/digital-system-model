"""Celery implementation of ITaskRunner: submits the combined workflow task
to the broker and reads task state from the Celery result backend."""

from __future__ import annotations

from celery import states
from celery.result import AsyncResult

from ports.task_runner import ITaskRunner, TaskStatus
from worker import celery_app, run_msd_workflow


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

    def submit_run(self, project_id: str, platform_id: str, version_id: str) -> str:
        async_result = run_msd_workflow.delay(project_id, platform_id, version_id)
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
