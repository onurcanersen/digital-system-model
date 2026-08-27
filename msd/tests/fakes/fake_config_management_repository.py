"""In-memory fake for IConfigManagementRepository (SRS DSM-MSD req 6-11, 12), for fast use-case tests."""

from __future__ import annotations

from typing import Dict, List, Optional

from model.system_hierarchy import SystemHierarchyRecord
from model.inventory import SoftwareUnitVersion
from model.project_context import PlatformRecord, ProjectRecord, VersionRecord
from ports.config_management_repository import ConfigManagementAccessError, IConfigManagementRepository


class FakeConfigManagementRepository(IConfigManagementRepository):
    def __init__(
        self,
        projects: Optional[List[ProjectRecord]] = None,
        platforms: Optional[List[PlatformRecord]] = None,
        versions: Optional[List[VersionRecord]] = None,
        unit_versions: Optional[Dict[str, List[SoftwareUnitVersion]]] = None,
        system_hierarchies: Optional[Dict[str, SystemHierarchyRecord]] = None,
        raise_error: Optional[Exception] = None,
    ):
        self._projects = projects if projects is not None else [ProjectRecord("proj-1", "skywatch")]
        self._platforms = platforms if platforms is not None else [
            PlatformRecord("plat-1", "proj-1", "nftw")
        ]
        self._versions = versions if versions is not None else [
            VersionRecord("1.0.0", "proj-1", "plat-1", "1.0.0", is_effective=True)
        ]
        self._unit_versions = unit_versions or {}
        self._system_hierarchies = system_hierarchies or {}
        self._raise_error = raise_error

    def _maybe_raise(self) -> None:
        if self._raise_error is not None:
            raise self._raise_error

    def list_projects(self) -> List[ProjectRecord]:
        self._maybe_raise()
        return self._projects

    def list_platforms(self, project_id: str) -> List[PlatformRecord]:
        self._maybe_raise()
        return [p for p in self._platforms if p.project_id == project_id]

    def list_versions(self, project_id: str, platform_id: str) -> List[VersionRecord]:
        self._maybe_raise()
        return [v for v in self._versions if v.project_id == project_id and v.platform_id == platform_id]

    def list_unit_versions(self, project_id: str, platform_id: str, version_id: str) -> List[SoftwareUnitVersion]:
        self._maybe_raise()
        return self._unit_versions.get(version_id, [])

    def get_system_hierarchy(self, unit_name: str) -> Optional[SystemHierarchyRecord]:
        self._maybe_raise()
        return self._system_hierarchies.get(unit_name)
