"""Use case: build the Software Unit Version Inventory (SRS DSM-MSD req 10-11)."""

from __future__ import annotations

from model.inventory import SoftwareUnitVersionInventory
from model.project_context import AcquisitionContext
from ports.config_management_repository import IConfigManagementRepository


class BuildSoftwareUnitInventoryUseCase:
    """Records the name/version of software units for a selected project/platform/version (req 10),
    and supports updating the inventory with a candidate unit version under evaluation (req 11)."""

    def __init__(self, config_repo: IConfigManagementRepository):
        self._config_repo = config_repo

    def execute(self, context: AcquisitionContext) -> SoftwareUnitVersionInventory:
        units = self._config_repo.list_unit_versions(
            context.project.project_id, context.platform.platform_id, context.version.version_id
        )
        return SoftwareUnitVersionInventory(context=context, units=units)

    @staticmethod
    def apply_candidate(
        inventory: SoftwareUnitVersionInventory, unit_name: str, candidate_version: str
    ) -> SoftwareUnitVersionInventory:
        return inventory.with_candidate(unit_name, candidate_version)
