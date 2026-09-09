"""Tests for VAE's Celery worker module: `celery -A vae.worker` must resolve
a Celery app configured from vae's own [worker] section of config.ini, and
the vae.run_msd_workflow task must call msd's workflow with the workspace root
and the task's own id as the run id."""

import logging
import re
from pathlib import Path
from unittest import mock

from celery import Celery, states

from fakes.fake_task_output_store import FakeTaskOutputStore

from msd.domain.inventory import CandidateUnitVersion

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


class _RecordingBackend(_NullBackend):
    """A _NullBackend that records store_result calls: what update_state
    (the run's progress channel) writes to the backend."""

    def __init__(self):
        self.stored = []

    def store_result(self, *args, **kwargs):
        self.stored.append((args, kwargs))


def _apply_task(components, tmp_path: Path, extra_args=(), backend=None):
    with mock.patch("vae.worker.load_components", return_value=components), \
         mock.patch.object(Celery, "backend", new=property(lambda self: backend or _NullBackend())), \
         mock.patch("vae.worker._make_task_output_store", return_value=FakeTaskOutputStore()):
        return worker.run_msd_workflow.apply(
            args=[
                "proj-1", "plat-1", "1.0.0",
                "localhost:3306/cmdb", "dsm", "dsm",
                "http://localhost:3001/dsm-src", "dsm", "dsm",
                *extra_args,
            ],
            task_id="task-eager",
        )


def test_run_msd_workflow_task_passes_the_workspace_and_the_task_id_as_run_id(tmp_path: Path):
    components = mock.Mock()
    components.workspace = tmp_path / "ws"
    components.workflow.return_value.execute.return_value.to_dict.return_value = {"run_id": "sentinel"}

    result = _apply_task(components, tmp_path)

    assert result.successful()
    assert result.result == {"run_id": "sentinel"}
    # The workspace root goes in whole; msd places the run under
    # <project>/<platform>/<version>/<run_id> itself.
    components.workflow.return_value.execute.assert_called_once_with(
        tmp_path / "ws", "proj-1", "plat-1", "1.0.0",
        run_id="task-eager", produced_by=None, candidate=None, progress=mock.ANY,
    )


def test_run_msd_workflow_task_forwards_the_producing_user(tmp_path: Path):
    components = mock.Mock()
    components.workspace = tmp_path / "ws"
    components.workflow.return_value.execute.return_value.to_dict.return_value = {}

    _apply_task(components, tmp_path, extra_args=["operator"])

    assert components.workflow.return_value.execute.call_args.kwargs["produced_by"] == "operator"


def test_run_msd_workflow_task_converts_the_candidate_dict_to_a_domain_value(tmp_path: Path):
    """SRS DSM-MSD req 11: the candidate arrives as JSON off the broker and
    must reach msd as the value object its workflow takes."""
    components = mock.Mock()
    components.workspace = tmp_path / "ws"
    components.workflow.return_value.execute.return_value.to_dict.return_value = {}

    _apply_task(
        components, tmp_path,
        extra_args=["operator", {"unit_name": "sensor_app", "version": "1.0.3"}],
    )

    assert components.workflow.return_value.execute.call_args.kwargs["candidate"] == (
        CandidateUnitVersion("sensor_app", "1.0.3")
    )


def test_run_msd_workflow_task_ignores_an_unusable_candidate(tmp_path: Path):
    """A malformed candidate is refused by the API before submission; if one
    reaches the worker anyway, the run proceeds on the versions the system
    version defines rather than failing outright."""
    components = mock.Mock()
    components.workspace = tmp_path / "ws"
    components.workflow.return_value.execute.return_value.to_dict.return_value = {}

    _apply_task(components, tmp_path, extra_args=["operator", {"unit_name": "sensor_app"}])

    assert components.workflow.return_value.execute.call_args.kwargs["candidate"] is None


def _components_reporting_progress(tmp_path: Path, percent: int = 42, phase: str = "clone") -> mock.Mock:
    """A workflow mock that, like the real one, reports progress from inside
    the running task — the only place the task's request context (and with it
    the backend the report is stored on) is live."""
    components = mock.Mock()
    components.workspace = tmp_path / "ws"

    def _execute(*args, **kwargs):
        assert kwargs["progress"] is not None
        kwargs["progress"](percent, phase)
        return mock.Mock()

    components.workflow.return_value.execute.side_effect = _execute
    return components


def test_run_msd_workflow_task_reports_progress_to_the_result_backend(tmp_path: Path):
    """The run's progress is published as the task's own state meta (via
    update_state), so the API's run stream — which re-reads the task's status
    — picks it up without a channel of its own."""
    backend = _RecordingBackend()

    result = _apply_task(_components_reporting_progress(tmp_path), tmp_path, backend=backend)

    assert result.successful()
    matching = [(a, k) for a, k in backend.stored if a and a[1] == {"percent": 42, "phase": "clone"}]
    assert matching, "the progress report never reached the backend"
    args, _kwargs = matching[0]
    assert args[0] == "task-eager"
    assert args[2] == states.STARTED


class _FailingBackend(_NullBackend):
    def store_result(self, *args, **kwargs):
        raise RuntimeError("redis down")


def test_run_msd_workflow_task_survives_a_dead_progress_channel(tmp_path: Path):
    """A progress report that cannot be stored must not fail the run — the
    same policy as the task's output capture."""
    result = _apply_task(
        _components_reporting_progress(tmp_path), tmp_path, backend=_FailingBackend()
    )

    assert result.successful()


def _record(message: str, level: int = logging.INFO) -> logging.LogRecord:
    return logging.LogRecord(
        "msd.services.clone_software_units", level, __file__, 1, message, None, None
    )


def test_task_output_handler_appends_formatted_lines():
    store = mock.Mock()
    handler = worker.TaskOutputHandler(store, "task-1")

    handler.emit(_record("clone: nav_app 1.0.0 cloned to /ws"))

    store.append.assert_called_once()
    task_id, line = store.append.call_args.args
    assert task_id == "task-1"
    assert re.fullmatch(
        r"\d{2}:\d{2}:\d{2} INFO     clone: nav_app 1\.0\.0 cloned to /ws", line
    )


def test_task_output_handler_swallows_store_errors():
    store = mock.Mock()
    store.append.side_effect = RuntimeError("redis down")
    handler = worker.TaskOutputHandler(store, "task-1")

    handler.emit(_record("clone: nav_app 1.0.0 cloned to /ws"))  # must not raise
