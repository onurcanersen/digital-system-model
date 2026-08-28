"""Tests for the Celery worker module: `celery -A worker` must resolve a Celery
app configured from the [worker] section of config.ini, and the
msd.run_msd_workflow task must run the workflow in a task-id-keyed workspace."""

from pathlib import Path
from unittest import mock

from celery import Celery

from composition import Components
from config import get_config
from fakes.fake_config_management_repository import FakeConfigManagementRepository
from fakes.fake_source_code_repository import DiskCloningSourceCodeRepository
from domain.inventory import SoftwareUnitVersion
import worker


def test_worker_exposes_celery_app_configured_from_config_ini():
    assert isinstance(worker.celery_app, Celery)
    assert worker.celery_app.conf.broker_url == get_config().worker.broker_url
    assert worker.celery_app.conf.result_backend == get_config().worker.result_backend
    assert worker.celery_app.conf.result_expires == 86400
    assert "msd.run_msd_workflow" in worker.celery_app.tasks


def _components(tmp_path: Path) -> Components:
    return Components(
        config_repo=FakeConfigManagementRepository(
            unit_versions={"1.0.0": [SoftwareUnitVersion("nav_app", "1.0.0")]},
        ),
        source_repo=DiskCloningSourceCodeRepository(mandatory_files=["Makefile", "src/nav_app.xml"]),
        workspace=tmp_path / "ws",
    )


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


def test_run_msd_workflow_task_runs_workflow_keyed_by_task_id(tmp_path: Path):
    components = _components(tmp_path)

    with mock.patch("worker.load_components", return_value=components), \
         mock.patch.object(Celery, "backend", new=property(lambda self: _NullBackend())):
        result = worker.run_msd_workflow.apply(
            args=["proj-1", "plat-1", "1.0.0"], task_id="task-eager"
        )

    assert result.successful()
    selection_dir = tmp_path / "ws" / "task-eager" / "proj-1" / "plat-1" / "1.0.0"
    assert result.result["workspace"] == str(selection_dir)
    assert (selection_dir / "nav_app" / "Makefile").is_file()
    assert result.result["validation_errors"] == []
