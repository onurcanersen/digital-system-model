"""Tests for VAE's Celery worker module: `celery -A vae.worker` must resolve
a Celery app configured from vae's own [worker] section of config.ini, and
the vae.run_msd_workflow task must call msd's workflow with a workspace dir
keyed by the task's id."""

from pathlib import Path
from unittest import mock

from celery import Celery

from vae import worker
from vae.config import get_config


def test_worker_exposes_celery_app_configured_from_config_ini():
    assert isinstance(worker.celery_app, Celery)
    assert worker.celery_app.conf.broker_url == get_config().worker.broker_url
    assert worker.celery_app.conf.result_backend == get_config().worker.result_backend
    assert worker.celery_app.conf.result_expires == 86400
    assert "vae.run_msd_workflow" in worker.celery_app.tasks


class _NullBackend:
    """Stands in for the result backend so eager apply never touches Redis."""

    def store_result(self, *args, **kwargs):
        pass

    def mark_as_done(self, *args, **kwargs):
        pass

    def mark_as_failure(self, *args, **kwargs):
        pass

    def mark_as_retry(self, *args, **kwargs):
        pass


def test_run_msd_workflow_task_calls_workflow_with_workspace_keyed_by_task_id(tmp_path: Path):
    components = mock.Mock()
    components.workspace = tmp_path / "ws"
    components.workflow.return_value.execute.return_value.to_dict.return_value = {"workspace": "sentinel"}

    with mock.patch("vae.worker.load_components", return_value=components), \
         mock.patch.object(Celery, "backend", new=property(lambda self: _NullBackend())):
        result = worker.run_msd_workflow.apply(
            args=[
                "proj-1", "plat-1", "1.0.0",
                "localhost:3306/cmdb", "dsm", "dsm",
                "http://localhost:3001/dsm-src", "dsm", "dsm",
            ],
            task_id="task-eager",
        )

    assert result.successful()
    assert result.result == {"workspace": "sentinel"}
    components.workflow.return_value.execute.assert_called_once_with(
        tmp_path / "ws" / "task-eager", "proj-1", "plat-1", "1.0.0"
    )
