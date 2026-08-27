"""Celery application and the combined clone → generate workflow task.

The broker and the result backend are Redis; both are configurable via env
vars (defaults match the local Redis from dev/compose.yaml):
  MSD_CELERY_BROKER_URL      (default redis://localhost:6379/0)
  MSD_CELERY_RESULT_BACKEND  (default redis://localhost:6379/1)

Start a worker from msd/src, in the same venv, with the same
MSD_WORKSPACE/MSD_CONFIG env as the API:
  python3.9 -m celery -A tasks worker --loglevel=info

The task body is a thin entry point: it loads the composition and runs the
RunWorkflowUseCase in a workspace dir keyed by this task's id — all
artifacts (cloned unit repositories and model_setup_data.json) live under
<workspace>/<task_id>/<project>/<platform>/<version>, so concurrent runs
never collide and runs never reuse previous artifacts (see
use_cases/run_workflow.py for the orchestration itself).
"""

from __future__ import annotations

import os

from celery import Celery

from composition import load_components

ENV_BROKER_URL = "MSD_CELERY_BROKER_URL"
ENV_RESULT_BACKEND = "MSD_CELERY_RESULT_BACKEND"
DEFAULT_BROKER_URL = "redis://localhost:6379/0"
DEFAULT_RESULT_BACKEND = "redis://localhost:6379/1"
RESULT_EXPIRES_SECONDS = 86400

celery_app = Celery(
    "msd",
    broker=os.environ.get(ENV_BROKER_URL, DEFAULT_BROKER_URL),
    backend=os.environ.get(ENV_RESULT_BACKEND, DEFAULT_RESULT_BACKEND),
)
celery_app.conf.update(
    result_expires=RESULT_EXPIRES_SECONDS,
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)


@celery_app.task(bind=True, name="msd.run_msd_workflow")
def run_msd_workflow(self, project_id: str, platform_id: str, version_id: str) -> dict:
    """Celery entry point: full MSD workflow for one selection, in a workspace
    dir keyed by this task's id."""
    components = load_components()
    return components.workflow_uc().execute(
        components.workspace / self.request.id, project_id, platform_id, version_id
    ).to_dict()
