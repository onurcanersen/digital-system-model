"""Software Unit Version Inventory (SRS DSM-MSD req 10-11)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional

from msd.domain.project_context import ProjectContext


@dataclass
class SoftwareUnitVersion:
    """One software unit at a specific version, from platform_pkg_version (req 10)."""
    unit_name: str
    version: str
    is_candidate: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"unit_name": self.unit_name, "version": self.version, "is_candidate": self.is_candidate}


@dataclass(frozen=True)
class CandidateUnitVersion:
    """The software unit version being evaluated for installation into the
    target environment (req 11) — the one version a run overrides, named by
    the caller rather than read from the configuration management database:
    a candidate is by definition not yet part of any system version.

    A run carries at most one, so this is a single value, not a collection."""
    unit_name: str
    version: str

    def to_dict(self) -> Dict[str, Any]:
        return {"unit_name": self.unit_name, "version": self.version}

    @classmethod
    def from_dict(cls, payload: Any) -> Optional["CandidateUnitVersion"]:
        """Rebuild from the payload form, or None when there is no usable
        candidate in it. Tolerant rather than strict because this crosses the
        task queue's JSON boundary: a run without a candidate sends None, and
        a malformed one must not take the whole run down after it has already
        been accepted (the API validates the shape before that point)."""
        if not isinstance(payload, dict):
            return None
        unit_name = payload.get("unit_name")
        version = payload.get("version")
        if not unit_name or not version:
            return None
        return cls(unit_name=str(unit_name), version=str(version))


@dataclass
class SoftwareUnitVersionInventory:
    """The recorded inventory of software units for one ProjectContext (req 10-11)."""
    context: ProjectContext
    units: List[SoftwareUnitVersion] = field(default_factory=list)

    def with_candidate(self, unit_name: str, candidate_version: str) -> "SoftwareUnitVersionInventory":
        """Return a new inventory with `unit_name` set to the candidate version
        under evaluation, alongside the other units at the versions the system
        version defines (req 11).

        The unit keeps its place in the inventory; a unit the system version
        does not define is appended, since a candidate may be a unit being
        introduced rather than one being upgraded."""
        candidate = SoftwareUnitVersion(unit_name=unit_name, version=candidate_version, is_candidate=True)
        updated_units = [candidate if u.unit_name == unit_name else u for u in self.units]
        if all(u.unit_name != unit_name for u in self.units):
            updated_units.append(candidate)
        return replace(self, units=updated_units)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "context": self.context.to_dict(),
            "units": [u.to_dict() for u in self.units],
        }
