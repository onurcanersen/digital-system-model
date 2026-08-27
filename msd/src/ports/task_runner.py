"""Port: submitting and tracking long-running MSD workflow executions
(clone → generate). The production implementation is Celery
(adapters/celery_task_runner.py); tests use a synchronous in-memory fake
(tests/fakes/fake_task_runner.py)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class TaskStatus:
    task_id: str
    state: str  # PENDING | STARTED | SUCCESS | FAILURE | ...
    result: Optional[Dict] = None
    error: Optional[str] = None


class ITaskRunner(ABC):
    @abstractmethod
    def submit_run(self, project_id: str, platform_id: str, version_id: str) -> str:
        """Queue one clone → generate execution for a selection. Returns the
        task id; raises if the execution backend is unreachable."""

    @abstractmethod
    def status(self, task_id: str) -> TaskStatus:
        """Current state/result of a submitted execution. Unknown ids report
        as PENDING (the backend cannot distinguish unknown from queued)."""
