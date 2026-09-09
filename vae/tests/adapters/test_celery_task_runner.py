"""Tests for CeleryTaskRunner's state/result mapping (stubbed AsyncResult — no broker)."""

from unittest import mock

from celery import states

from vae.adapters.celery_task_runner import CeleryTaskRunner
from vae.domain.task_status import TaskStatus


class _FakeAsyncResult:
    def __init__(self, state, result=None, task_id="t-1"):
        self.id = task_id
        self.state = state
        self.result = result


def _status(state, result=None, task_id="t-1"):
    runner = CeleryTaskRunner()
    with mock.patch("vae.adapters.celery_task_runner.AsyncResult") as async_result_cls:
        async_result_cls.return_value = _FakeAsyncResult(state, result)
        return runner.status(task_id)


def test_submit_run_delegates_to_celery_delay():
    runner = CeleryTaskRunner()
    with mock.patch("vae.adapters.celery_task_runner.run_msd_workflow") as task:
        task.delay.return_value = _FakeAsyncResult(states.PENDING, task_id="abc")
        assert runner.submit_run(
            "proj-1", "plat-1", "1.0.0",
            "localhost:3306/cmdb", "dsm", "dsm",
            "http://localhost:3001/dsm-src", "dsm", "dsm",
            produced_by="operator",
        ) == "abc"
    task.delay.assert_called_once_with(
        "proj-1", "plat-1", "1.0.0",
        "localhost:3306/cmdb", "dsm", "dsm",
        "http://localhost:3001/dsm-src", "dsm", "dsm",
        "operator", None,
    )


def test_submit_run_forwards_the_candidate_under_evaluation():
    """SRS DSM-MSD req 11: the candidate rides to the worker as a plain dict,
    since task arguments cross the broker as JSON."""
    runner = CeleryTaskRunner()
    candidate = {"unit_name": "sensor_app", "version": "1.0.3"}
    with mock.patch("vae.adapters.celery_task_runner.run_msd_workflow") as task:
        task.delay.return_value = _FakeAsyncResult(states.PENDING, task_id="abc")
        runner.submit_run(
            "proj-1", "plat-1", "1.0.0",
            "localhost:3306/cmdb", "dsm", "dsm",
            "http://localhost:3001/dsm-src", "dsm", "dsm",
            produced_by="operator",
            candidate=candidate,
        )
    assert task.delay.call_args.args[-1] == candidate


def test_cancel_revokes_with_terminate_and_reports_status():
    runner = CeleryTaskRunner()
    with mock.patch("vae.adapters.celery_task_runner.AsyncResult") as async_result_cls:
        async_result = async_result_cls.return_value
        async_result.state = states.REVOKED
        status = runner.cancel("t-1")

    async_result.revoke.assert_called_once_with(terminate=True)
    assert status == TaskStatus(task_id="t-1", state="REVOKED")


def test_status_success_carries_result_dict():
    status = _status(states.SUCCESS, {"workspace": "/ws", "units": []})

    assert status.task_id == "t-1"
    assert status.state == "SUCCESS"
    assert status.result == {"workspace": "/ws", "units": []}
    assert status.error is None


def test_status_failure_carries_exception_message():
    status = _status(states.FAILURE, ValueError("boom"))

    assert status.state == "FAILURE"
    assert status.error == "boom"
    assert status.result is None


def test_status_failure_with_empty_message_falls_back_to_repr():
    status = _status(states.FAILURE, ValueError())

    assert status.state == "FAILURE"
    assert "ValueError" in status.error


def test_status_started_carries_the_run_progress_in_info():
    """A running task's published state meta (update_state's meta — the run's
    progress) rides back as info, the non-terminal counterpart of result."""
    status = _status(states.STARTED, {"percent": 42, "phase": "clone"})

    assert status.state == "STARTED"
    assert status.info == {"percent": 42, "phase": "clone"}
    assert status.result is None
    assert status.error is None


def test_status_started_ignores_meta_that_is_not_a_dict():
    status = _status(states.STARTED, "not-a-dict")

    assert status.info is None


def test_status_started_ignores_celerys_own_started_info():
    """Celery publishes the worker's pid/hostname as the task's STARTED meta;
    that is not the run's progress, so it must not surface as such."""
    status = _status(states.STARTED, {"pid": 42, "hostname": "celery@host"})

    assert status.info is None


def test_status_non_ready_states_carry_no_payload():
    for state in (states.PENDING, states.STARTED):
        status = _status(state)
        assert status.state == state
        assert status.result is None
        assert status.error is None
        assert status.info is None
