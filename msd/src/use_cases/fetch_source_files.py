"""Use case: fetch source repo files for the inventory's units (SRS DSM-MSD req 13-16)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List

from model.acquired_file import AcquiredFile, FileAccessError
from model.inventory import SoftwareUnitVersion, SoftwareUnitVersionInventory
from model.status import AcquisitionStatus
from ports.source_code_repository import (
    ISourceCodeRepository,
    SourceRepoAccessError,
    SourceRepoAuthError,
    SourceRepoIntegrityError,
)


def missing_mandatory_file_records(
    unit: SoftwareUnitVersion,
    mandatory: List[str],
    found_names: set,
    now: datetime,
) -> List[AcquiredFile]:
    """MISSING_DATA records for mandatory files absent from `found_names` (req 15).
    Shared by the fetch step and the parse step (which scans already-cloned repos)."""
    return [
        AcquiredFile(
            unit_name=unit.unit_name,
            file_name=Path(relative_path).name,
            file_path=relative_path,
            package_version=unit.version,
            updated_at=now,
            status=AcquisitionStatus.MISSING_DATA,
        )
        for relative_path in mandatory
        if Path(relative_path).name not in found_names
    ]


class FetchSourceFilesUseCase:
    """Accesses and transfers source code, install scripts, and config files for
    each inventory unit (req 13), recording name/path/version/timestamp per
    mandatory file (req 14). Reports "missing data" when a mandatory file is
    absent (req 15), and records access/authorization/integrity errors (req 16)."""

    def __init__(self, source_repo: ISourceCodeRepository):
        self._source_repo = source_repo

    def execute(self, inventory: SoftwareUnitVersionInventory, dest_root: Path) -> List[AcquiredFile]:
        results: List[AcquiredFile] = []
        for unit in inventory.units:
            mandatory = self._source_repo.list_mandatory_files(unit.unit_name)
            now = datetime.now()
            try:
                found = self._source_repo.clone_unit(unit, dest_root)
            except SourceRepoAccessError as exc:
                results.extend(self._error_records(unit.unit_name, unit.version, mandatory, now, "access", exc))
                continue
            except SourceRepoAuthError as exc:
                results.extend(self._error_records(unit.unit_name, unit.version, mandatory, now, "authorization", exc))
                continue
            except SourceRepoIntegrityError as exc:
                results.extend(self._error_records(unit.unit_name, unit.version, mandatory, now, "integrity", exc))
                continue

            found_names = {Path(f.file_path).name for f in found}
            results.extend(found)
            results.extend(missing_mandatory_file_records(unit, mandatory, found_names, now))
        return results

    @staticmethod
    def _error_records(unit_name: str, version: str, mandatory: List[str], now: datetime,
                        error_type: str, exc: Exception) -> List[AcquiredFile]:
        error = FileAccessError(file_path=unit_name, error_type=error_type, message=str(exc))
        return [
            AcquiredFile(
                unit_name=unit_name,
                file_name=Path(relative_path).name,
                file_path=relative_path,
                package_version=version,
                updated_at=now,
                status=AcquisitionStatus.ERROR,
                errors=[error],
            )
            for relative_path in mandatory
        ]
