"""Project/platform/version context acquired from the config-mgmt DB (SRS DSM-MSD req 5-9, 12)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict


@dataclass
class ProjectRecord:
    """A project known to the configuration management database (req 6)."""
    project_id: str
    name: str

    def to_dict(self) -> Dict[str, Any]:
        return {"project_id": self.project_id, "name": self.name}


@dataclass
class PlatformRecord:
    """A platform belonging to a project (req 7)."""
    platform_id: str
    project_id: str
    name: str

    def to_dict(self) -> Dict[str, Any]:
        return {"platform_id": self.platform_id, "project_id": self.project_id, "name": self.name}


@dataclass
class VersionRecord:
    """A system version belonging to a project/platform (req 8-9)."""
    version_id: str
    project_id: str
    platform_id: str
    label: str
    is_effective: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version_id": self.version_id,
            "project_id": self.project_id,
            "platform_id": self.platform_id,
            "label": self.label,
            "is_effective": self.is_effective,
        }


@dataclass
class ProjectContext:
    """The selected project/platform/version an acquisition run operates on (req 5)."""
    project: ProjectRecord
    platform: PlatformRecord
    version: VersionRecord

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project": self.project.to_dict(),
            "platform": self.platform.to_dict(),
            "version": self.version.to_dict(),
        }


@dataclass
class AcquisitionError:
    """Error status raised when the config-mgmt DB is deficient/unreachable (req 12)."""
    source_name: str
    source_type: str
    reason: str
    occurred_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_name": self.source_name,
            "source_type": self.source_type,
            "reason": self.reason,
            "occurred_at": self.occurred_at.isoformat(),
        }
