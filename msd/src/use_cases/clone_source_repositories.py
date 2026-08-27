"""Use case: clone source repositories for a selected project/platform/version (SRS DSM-MSD req 13).

Deliberately a standalone step between selection and parsing: it only touches
the source code repository. Units already present at the destination are not
re-cloned, so a later parse step can reuse previously cloned repositories.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from model.inventory import SoftwareUnitVersion
from ports.source_code_repository import (
    ISourceCodeRepository,
    SourceRepoAccessError,
    SourceRepoAuthError,
    SourceRepoIntegrityError,
)
from use_cases.acquire_project_context import AcquireProjectContextUseCase
from use_cases.build_software_unit_inventory import BuildSoftwareUnitInventoryUseCase

CLONE_STATUS_CLONED = "cloned"
CLONE_STATUS_ALREADY_PRESENT = "already_present"
CLONE_STATUS_ERROR = "error"

logger = logging.getLogger(__name__)


@dataclass
class CloneUnitResult:
    unit: SoftwareUnitVersion
    status: str
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "unit_name": self.unit.unit_name,
            "version": self.unit.version,
            "status": self.status,
            "detail": self.detail,
        }


class CloneSourceRepositoriesUseCase:
    """Clones the inventory's unit repositories into `dest_root/<unit_name>` (req 13),
    skipping units that already have a non-empty checkout there, and recording
    per-unit access/authorization/integrity errors instead of aborting (req 16)."""

    def __init__(
        self,
        project_context_uc: AcquireProjectContextUseCase,
        inventory_uc: BuildSoftwareUnitInventoryUseCase,
        source_repo: ISourceCodeRepository,
    ):
        self._project_context_uc = project_context_uc
        self._inventory_uc = inventory_uc
        self._source_repo = source_repo

    def execute(
        self,
        dest_root: Path,
        project_id: Optional[str] = None,
        platform_id: Optional[str] = None,
        version_id: Optional[str] = None,
    ) -> List[CloneUnitResult]:
        context_result = self._project_context_uc.execute(project_id, platform_id, version_id)
        if context_result.context is None:
            raise RuntimeError(f"Cannot acquire project context: {context_result.error}")
        inventory = self._inventory_uc.execute(context_result.context)

        dest_root.mkdir(parents=True, exist_ok=True)
        results: List[CloneUnitResult] = []
        for unit in inventory.units:
            unit_dir = dest_root / unit.unit_name
            if unit_dir.is_dir() and any(unit_dir.iterdir()):
                logger.info("clone: %s %s already present at %s, skipping", unit.unit_name, unit.version, unit_dir)
                results.append(
                    CloneUnitResult(unit=unit, status=CLONE_STATUS_ALREADY_PRESENT, detail=str(unit_dir))
                )
                continue
            try:
                self._source_repo.clone_unit(unit, dest_root)
                logger.info("clone: %s %s cloned to %s", unit.unit_name, unit.version, unit_dir)
                results.append(CloneUnitResult(unit=unit, status=CLONE_STATUS_CLONED, detail=str(unit_dir)))
            except (SourceRepoAccessError, SourceRepoAuthError, SourceRepoIntegrityError) as exc:
                logger.warning("clone: %s %s failed: %s", unit.unit_name, unit.version, exc)
                results.append(CloneUnitResult(unit=unit, status=CLONE_STATUS_ERROR, detail=str(exc)))
        return results
