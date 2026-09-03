"""Port for triggering and tracking vae's own background runs of msd's
clone + generate workflow (vae.worker.run_msd_workflow). The production
implementation submits them to Celery
(adapters/celery_task_runner.py); tests inject a synchronous fake."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Optional

from vae.domain.task_status import TaskStatus


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
        produced_by: Optional[str] = None,
        candidate: Optional[Dict] = None,
    ) -> str:
        """Queue one clone → generate execution for a selection, connecting to
        config_mgmt_db and source_code_repo with the given caller-supplied
        credentials. `produced_by` names the user the run is on behalf of, and
        is recorded in the produced file. `candidate` is the optional
        {"unit_name", "version"} the run evaluates in place of the version the
        system version defines (SRS DSM-MSD req 11). Returns the task id;
        raises if the execution backend is unreachable."""

    @abstractmethod
    def status(self, task_id: str) -> TaskStatus:
        """Current state/result of a submitted execution. Unknown ids report
        as PENDING (the backend cannot distinguish unknown from queued)."""

    @abstractmethod
    def cancel(self, task_id: str) -> TaskStatus:
        """Revoke a submitted execution: a queued one will not run, a running
        one is terminated in its worker process. Returns the task's current
        status (the backend may still report the pre-revocation state for a
        moment, since workers apply the revocation asynchronously)."""
