"""Port for capturing a task's output lines (log output produced while the
task runs), so the serving layer can show them in the UI."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List


class ITaskOutputStore(ABC):
    @abstractmethod
    def append(self, task_id: str, line: str) -> None:
        """Record one output line for a task, in order."""

    @abstractmethod
    def lines(self, task_id: str) -> List[str]:
        """All recorded output lines for a task, in order (empty for
        unknown tasks)."""
