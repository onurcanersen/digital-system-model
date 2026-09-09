"""Use case: clone the software units' repositories for a selected project/platform/version (SRS DSM-MSD req 13).

Deliberately a standalone step between selection and generating: it only touches
the source code repository. Units already present at the destination are not
re-cloned, so a later generate step can reuse previously cloned repositories.

The per-unit clones run up to UNIT_CONCURRENCY units at once (see
services/concurrency.py); the results come back in inventory order.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from msd.domain.inventory import CandidateUnitVersion, SoftwareUnitVersion
from msd.domain.status import CloneStatus
from msd.ports.source_code_repository import (
    ISourceCodeRepository,
    SourceRepoAccessError,
    SourceRepoAuthError,
    SourceRepoIntegrityError,
)
from msd.services.acquire_project_context import AcquireProjectContext
from msd.services.build_software_unit_inventory import BuildSoftwareUnitInventory
from msd.services.concurrency import run_units_concurrently
from msd.services.progress import PHASE_CLONE

logger = logging.getLogger(__name__)


@dataclass
class CloneUnitResult:
    unit: SoftwareUnitVersion
    status: CloneStatus
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "unit_name": self.unit.unit_name,
            "version": self.unit.version,
            "status": self.status.value,
            "detail": self.detail,
        }


class CloneSoftwareUnits:
    """Clones the inventory's unit repositories into `dest_root/<unit_name>` (req 13),
    skipping units that already have a non-empty checkout there, and recording
    per-unit access/authorization/integrity errors instead of aborting (req 16)."""

    def __init__(
        self,
        project_context: AcquireProjectContext,
        inventory: BuildSoftwareUnitInventory,
        source_repo: ISourceCodeRepository,
    ):
        self._project_context = project_context
        self._inventory = inventory
        self._source_repo = source_repo

    def execute(
        self,
        dest_root: Path,
        project_id: Optional[str] = None,
        platform_id: Optional[str] = None,
        version_id: Optional[str] = None,
        candidate: Optional[CandidateUnitVersion] = None,
        progress: Optional[Callable[[str, int, int], None]] = None,
    ) -> List[CloneUnitResult]:
        context_result = self._project_context.execute(project_id, platform_id, version_id)
        if context_result.context is None:
            raise RuntimeError(f"Cannot acquire project context: {context_result.error}")
        # With a candidate, the inventory names its version for that unit, so
        # the clone below fetches the candidate's ref rather than the one the
        # system version pins (req 11).
        inventory = self._inventory.execute(context_result.context, candidate)

        units = inventory.units
        # The pool helper reports (0, N) before the first (possibly long)
        # clone, so the caller's bar can appear immediately.
        dest_root.mkdir(parents=True, exist_ok=True)
        return run_units_concurrently(units, lambda unit: self._clone_one(unit, dest_root), PHASE_CLONE, progress)

    def _clone_one(self, unit: SoftwareUnitVersion, dest_root: Path) -> CloneUnitResult:
        """The per-unit clone: a non-empty checkout already at the destination
        is kept as is, everything else is cloned, and a per-unit
        access/authorization/integrity failure is recorded instead of aborting
        the phase (req 16)."""
        unit_dir = dest_root / unit.unit_name
        if unit_dir.is_dir() and any(unit_dir.iterdir()):
            logger.info("clone: %s %s already present at %s, skipping", unit.unit_name, unit.version, unit_dir)
            return CloneUnitResult(unit=unit, status=CloneStatus.ALREADY_PRESENT, detail=str(unit_dir))
        try:
            self._source_repo.clone_unit(unit, dest_root)
            logger.info("clone: %s %s cloned to %s", unit.unit_name, unit.version, unit_dir)
            return CloneUnitResult(unit=unit, status=CloneStatus.CLONED, detail=str(unit_dir))
        except (SourceRepoAccessError, SourceRepoAuthError, SourceRepoIntegrityError) as exc:
            logger.warning("clone: %s %s failed: %s", unit.unit_name, unit.version, exc)
            return CloneUnitResult(unit=unit, status=CloneStatus.ERROR, detail=str(exc))
