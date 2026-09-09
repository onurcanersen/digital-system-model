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

    @abstractmethod
    def lines_since(self, task_id: str, index: int) -> List[str]:
        """The recorded output lines from 0-based position `index` to the
        end, in order (empty for unknown tasks). A caller that has already
        seen everything up to `index - 1` asks for `index`, so a poll returns
        only the lines it does not have yet rather than the whole log."""
