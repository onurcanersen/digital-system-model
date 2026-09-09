"""In-process ITaskOutputStore for vae's tests: keeps a task's output lines
in a dict, so no redis is needed to exercise the worker's capture or the
API's task-state endpoint."""

from __future__ import annotations

from typing import Dict, List

from vae.ports.task_output_store import ITaskOutputStore


class FakeTaskOutputStore(ITaskOutputStore):
    def __init__(self) -> None:
        self._lines: Dict[str, List[str]] = {}

    def append(self, task_id: str, line: str) -> None:
        self._lines.setdefault(task_id, []).append(line)

    def lines(self, task_id: str) -> List[str]:
        return list(self._lines.get(task_id, ()))

    def lines_since(self, task_id: str, index: int) -> List[str]:
        return list(self._lines.get(task_id, ())[max(index, 0):])
