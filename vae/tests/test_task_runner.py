"""Tests for CeleryTaskRunner's state/result mapping (stubbed AsyncResult — no broker)."""

from unittest import mock

from celery import states

from vae.task_runner import CeleryTaskRunner, TaskStatus


class _FakeAsyncResult:
    def __init__(self, state, result=None, task_id="t-1"):
        self.id = task_id
        self.state = state
        self.result = result


def _status(state, result=None, task_id="t-1"):
    runner = CeleryTaskRunner()
    with mock.patch("vae.task_runner.AsyncResult") as async_result_cls:
        async_result_cls.return_value = _FakeAsyncResult(state, result)
        return runner.status(task_id)


def test_submit_run_delegates_to_celery_delay():
    runner = CeleryTaskRunner()
    with mock.patch("vae.task_runner.run_msd_workflow") as task:
        task.delay.return_value = _FakeAsyncResult(states.PENDING, task_id="abc")
        assert runner.submit_run(
            "proj-1", "plat-1", "1.0.0",
            "localhost:3306/cmdb", "dsm", "dsm",
            "http://localhost:3001/dsm-src", "dsm", "dsm",
        ) == "abc"
    task.delay.assert_called_once_with(
        "proj-1", "plat-1", "1.0.0",
        "localhost:3306/cmdb", "dsm", "dsm",
        "http://localhost:3001/dsm-src", "dsm", "dsm",
    )


def test_cancel_revokes_with_terminate_and_reports_status():
    runner = CeleryTaskRunner()
    with mock.patch("vae.task_runner.AsyncResult") as async_result_cls:
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


def test_status_non_ready_states_carry_no_payload():
    for state in (states.PENDING, states.STARTED):
        status = _status(state)
        assert status.state == state
        assert status.result is None
        assert status.error is None
