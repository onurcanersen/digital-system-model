"""Scriptable fake for ISourceCodeRepository (SRS DSM-MSD req 13-16), for fast use-case tests."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from model.acquired_file import AcquiredFile
from model.inventory import SoftwareUnitVersion
from ports.source_code_repository import ISourceCodeRepository


class FakeSourceCodeRepository(ISourceCodeRepository):
    def __init__(
        self,
        mandatory_files: Optional[List[str]] = None,
        clone_results: Optional[Dict[str, List[AcquiredFile]]] = None,
        raise_error: Optional[Exception] = None,
    ):
        self._mandatory_files = mandatory_files if mandatory_files is not None else ["Makefile", "src/unit.xml"]
        self._clone_results = clone_results or {}
        self._raise_error = raise_error

    def clone_unit(self, unit: SoftwareUnitVersion, dest_dir: Path) -> List[AcquiredFile]:
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
