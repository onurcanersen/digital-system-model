"""Use case: build the Software Unit Version Inventory (SRS DSM-MSD req 10-11)."""

from __future__ import annotations

from typing import Optional

from msd.domain.inventory import CandidateUnitVersion, SoftwareUnitVersionInventory
from msd.domain.project_context import ProjectContext
from msd.ports.config_management_repository import IConfigManagementRepository


class BuildSoftwareUnitInventory:
    """Records the name/version of software units for a selected project/platform/version (req 10),
    updating the inventory with a candidate unit version under evaluation when one is
    given (req 11).

    The candidate is applied here rather than by the callers because every step
    of a run builds its own inventory from this one use case: applying it
    anywhere else would let the clone step fetch the version the system pins
    while the generate step expected the candidate."""

    def __init__(self, config_repo: IConfigManagementRepository):
        self._config_repo = config_repo

    def execute(
        self,
        context: ProjectContext,
        candidate: Optional[CandidateUnitVersion] = None,
    ) -> SoftwareUnitVersionInventory:
        units = self._config_repo.list_unit_versions(
            context.project.project_id, context.platform.platform_id, context.version.version_id
        )
        inventory = SoftwareUnitVersionInventory(context=context, units=units)
        if candidate is None:
            return inventory
        return inventory.with_candidate(candidate.unit_name, candidate.version)
