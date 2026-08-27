"""Celery application for msd's asynchronous workflow tasks.

The broker and the result backend are Redis; both are configurable via env
vars (defaults match the local Redis from dev/compose.yaml):
  MSD_CELERY_BROKER_URL      (default redis://localhost:6379/0)
  MSD_CELERY_RESULT_BACKEND  (default redis://localhost:6379/1)

Start a worker from msd/src, in the same venv, with the same
MSD_WORKSPACE/MSD_CONFIG env as the API:
  python3.9 -m celery -A tasks.celery_app worker --loglevel=info
"""

from __future__ import annotations

import os

from celery import Celery

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
    include=["tasks.workflow"],
    result_expires=RESULT_EXPIRES_SECONDS,
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)
