"""In-memory stand-in for the task output store: the dev/test default for
Components, so a missing/standalone redis never blocks the API or tests."""

from __future__ import annotations

from typing import Dict, List

from vae.ports.task_output_store import ITaskOutputStore


class InMemoryTaskOutputStore(ITaskOutputStore):
    def __init__(self) -> None:
        self._lines: Dict[str, List[str]] = {}

    def append(self, task_id: str, line: str) -> None:
        self._lines.setdefault(task_id, []).append(line)

    def lines(self, task_id: str) -> List[str]:
        return list(self._lines.get(task_id, ()))
