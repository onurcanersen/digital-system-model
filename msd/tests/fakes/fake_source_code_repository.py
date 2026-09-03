"""Scriptable fake for ISourceCodeRepository (SRS DSM-MSD req 13-16), for fast use-case tests."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from msd.domain.acquired_file import AcquiredFile
from msd.domain.inventory import SoftwareUnitVersion
from msd.ports.source_code_repository import ISourceCodeRepository, SourceRepoAccessError


class FakeSourceCodeRepository(ISourceCodeRepository):
    def __init__(
        self,
        mandatory_files: Optional[List[str]] = None,
        clone_results: Optional[Dict[str, List[AcquiredFile]]] = None,
        raise_error: Optional[Exception] = None,
        available_versions: Optional[Dict[str, List[str]]] = None,
    ):
        self._mandatory_files = mandatory_files if mandatory_files is not None else ["Makefile", "src/unit.xml"]
        self._clone_results = clone_results or {}
        self._raise_error = raise_error
        self._available_versions = available_versions or {}
        # (unit_name, version) per clone attempt — what a candidate run is
        # asserted against, since the version is the ref the real adapter asks for.
        self.cloned: List[tuple] = []

    def clone_unit(self, unit: SoftwareUnitVersion, dest_dir: Path) -> List[AcquiredFile]:
        self.cloned.append((unit.unit_name, unit.version))
        if self._raise_error is not None:
            raise self._raise_error
        return self._clone_results.get(unit.unit_name, [])

    def scan_cloned_unit(self, unit: SoftwareUnitVersion, clone_path: Path) -> List[AcquiredFile]:
        """Disk scan of mandatory files under `clone_path` (no network),
        mirroring the real adapter's scan behavior."""
        acquired: List[AcquiredFile] = []
        now = datetime.now()
        for relative_path in self._mandatory_files:
            file_path = clone_path / relative_path
            if file_path.is_file():
                acquired.append(
                    AcquiredFile(unit.unit_name, file_path.name, str(file_path), unit.version, now)
                )
        return acquired

    def list_mandatory_files(self, unit_name: str) -> List[str]:
        return list(self._mandatory_files)

    def list_available_versions(self, unit_name: str) -> List[str]:
        if self._raise_error is not None:
            raise self._raise_error
        return list(self._available_versions.get(unit_name, []))


class DiskCloningSourceCodeRepository(FakeSourceCodeRepository):
    """Clone that actually writes the unit directory to disk, like the git
    adapter: each successful clone creates <unit>/Makefile and
    <unit>/src/<unit>.xml under dest_dir. Units in `fail_units` raise
    SourceRepoAccessError instead."""

    def __init__(self, fail_units=(), mandatory_files: Optional[List[str]] = None):
        super().__init__(mandatory_files=mandatory_files)
        self._fail_units = set(fail_units)

    def clone_unit(self, unit: SoftwareUnitVersion, dest_dir: Path) -> List[AcquiredFile]:
        self.cloned.append((unit.unit_name, unit.version))
        if unit.unit_name in self._fail_units:
            raise SourceRepoAccessError(f"cannot clone '{unit.unit_name}'")
        unit_dir = dest_dir / unit.unit_name
        (unit_dir / "src").mkdir(parents=True, exist_ok=True)
        (unit_dir / "Makefile").write_text("all:\n", encoding="utf-8")
        (unit_dir / "src" / f"{unit.unit_name}.xml").write_text("<manifest/>", encoding="utf-8")
        # Not super().clone_unit(): it would record the attempt a second time.
        return self._clone_results.get(unit.unit_name, [])
