"""State of one submitted task run, as the task runner port reports it.

The state strings are Celery's own and are part of the API/UI contract (the
run stream's `status` events carry them straight through), so they stay
verbatim rather than being mapped onto a vae-specific vocabulary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class TaskStatus:
    task_id: str
    state: str  # PENDING | STARTED | SUCCESS | FAILURE | ...
    result: Optional[Dict] = None
    error: Optional[str] = None
    # Mid-run state the task itself published (Celery's update_state meta):
    # for vae's runs the overall progress of the run so far. None while the
    # task has published nothing and once a terminal state has replaced it.
    info: Optional[Dict] = None
