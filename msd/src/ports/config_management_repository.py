"""Port for the system configuration management database (SRS DSM-MSD req 2.1, 6-9, 10-11, 12)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from model.system_hierarchy import SystemHierarchyRecord
from model.inventory import SoftwareUnitVersion
from model.project_context import PlatformRecord, ProjectRecord, VersionRecord


class ConfigManagementAccessError(Exception):
    """Raised on deficiency, access error, or format incompatibility (req 12)."""


class IConfigManagementRepository(ABC):
    """Port for the config-mgmt DB. Package repository (req 2.3) is folded in here —
    `list_unit_versions` reads the same table project/platform/version comes from,
    since there is no separate package-repo data source to model."""

    @abstractmethod
    def list_projects(self) -> List[ProjectRecord]:
        """Obtain project information (req 6)."""

    @abstractmethod
    def list_platforms(self, project_id: str) -> List[PlatformRecord]:
        """Obtain platform information for the selected project (req 7)."""

    @abstractmethod
    def list_versions(self, project_id: str, platform_id: str) -> List[VersionRecord]:
        """Obtain system version information for the selected project/platform,
        with the currently effective version marked (req 8-9)."""

    @abstractmethod
    def list_unit_versions(self, project_id: str, platform_id: str, version_id: str) -> List[SoftwareUnitVersion]:
        """Obtain the software unit name/version pairs for the selected
        project/platform/version, to build the Software Unit Version Inventory (req 10)."""

    @abstractmethod
    def get_system_hierarchy(self, unit_name: str) -> Optional[SystemHierarchyRecord]:
        """Obtain the system-hierarchy naming (CSC/CSCI/CSS/CSMS) for a
        software unit from the config-mgmt DB (req 6-8); it populates each
        unit's system-hierarchy attributes in the Model Setup Data graph
        (req 19)."""
