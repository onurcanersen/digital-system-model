"""Use case: acquire project/platform/version context (SRS DSM-MSD req 5-9, 12)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from domain.data_source import SourceType
from domain.project_context import ProjectContext, AcquisitionError
from domain.status import AcquisitionStatus
from ports.config_management_repository import ConfigManagementAccessError, IConfigManagementRepository


@dataclass
class ProjectContextResult:
    context: Optional[ProjectContext]
    status: AcquisitionStatus
    error: Optional[AcquisitionError] = None


class AcquireProjectContext:
    """Obtains project, platform, and version information from the config-mgmt DB,
    marking the currently effective version among them (req 6-9). Marks the
    acquisition with an error status on a config-mgmt-DB failure (req 12).

    Requires the caller to specify project_id/platform_id/version_id
    explicitly — an unspecified id is reported as MISSING_DATA, never
    silently defaulted to "the first one." Callers discover the effective
    version via IConfigManagementRepository.list_versions()
    (VersionRecord.is_effective) before choosing which version_id to pass.
    """

    def __init__(self, config_repo: IConfigManagementRepository):
        self._config_repo = config_repo

    def execute(
        self,
        project_id: Optional[str] = None,
        platform_id: Optional[str] = None,
        version_id: Optional[str] = None,
    ) -> ProjectContextResult:
        if project_id is None:
            return self._missing("project_id must be specified")
        if platform_id is None:
            return self._missing("platform_id must be specified")
        if version_id is None:
            return self._missing("version_id must be specified")

        try:
            projects = self._config_repo.list_projects()
            project = next((p for p in projects if p.project_id == project_id), None)
            if project is None:
                return self._missing(f"project '{project_id}' not found")

            platforms = self._config_repo.list_platforms(project.project_id)
            platform = next((p for p in platforms if p.platform_id == platform_id), None)
            if platform is None:
                return self._missing(f"platform '{platform_id}' not found for project '{project_id}'")

            versions = self._config_repo.list_versions(project.project_id, platform.platform_id)
            version = next((v for v in versions if v.version_id == version_id), None)
            if version is None:
                return self._missing(
                    f"version '{version_id}' not found for '{project_id}/{platform_id}'"
                )

            context = ProjectContext(project=project, platform=platform, version=version)
            return ProjectContextResult(context=context, status=AcquisitionStatus.OK)

        except ConfigManagementAccessError as exc:
            error = AcquisitionError(
                source_name="config_mgmt_db",
                source_type=SourceType.CONFIG_MGMT_DB.value,
                reason=str(exc),
                occurred_at=datetime.now(),
            )
            return ProjectContextResult(context=None, status=AcquisitionStatus.ERROR, error=error)

    @staticmethod
    def _missing(reason: str) -> ProjectContextResult:
        error = AcquisitionError(
            source_name="config_mgmt_db",
            source_type=SourceType.CONFIG_MGMT_DB.value,
            reason=reason,
            occurred_at=datetime.now(),
        )
        return ProjectContextResult(context=None, status=AcquisitionStatus.MISSING_DATA, error=error)
