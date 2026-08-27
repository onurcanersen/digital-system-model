"""Software Unit Version Inventory (SRS DSM-MSD req 10-11)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, List

from model.project_context import ProjectContext


@dataclass
class SoftwareUnitVersion:
    """One software unit at a specific version, from platform_pkg_version (req 10)."""
    unit_name: str
    version: str
    is_candidate: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"unit_name": self.unit_name, "version": self.version, "is_candidate": self.is_candidate}


@dataclass
class SoftwareUnitVersionInventory:
    """The recorded inventory of software units for one ProjectContext (req 10-11)."""
    context: ProjectContext
    units: List[SoftwareUnitVersion] = field(default_factory=list)

    def with_candidate(self, unit_name: str, candidate_version: str) -> "SoftwareUnitVersionInventory":
        """Return a new inventory with `unit_name` set to the candidate version under evaluation (req 11)."""
        updated_units = [u for u in self.units if u.unit_name != unit_name]
        updated_units.append(SoftwareUnitVersion(unit_name=unit_name, version=candidate_version, is_candidate=True))
        return replace(self, units=updated_units)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "context": self.context.to_dict(),
            "units": [u.to_dict() for u in self.units],
        }
