"""In-memory fake of msd's ISourceCodeRepository for vae's API tests.

Only the version listing is real: the API reads the source repository to offer
the versions a candidate may be chosen from (SRS DSM-MSD req 11), and never
clones or scans — that happens in the worker, out of process. The rest of the
port raises, so a test that reaches it fails loudly instead of passing on a
stub the API should never have called.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from msd.domain.acquired_file import AcquiredFile
from msd.domain.inventory import SoftwareUnitVersion
from msd.ports.source_code_repository import ISourceCodeRepository


class FakeSourceCodeRepository(ISourceCodeRepository):
    def __init__(
        self,
        available_versions: Optional[Dict[str, List[str]]] = None,
        raise_error: Optional[Exception] = None,
    ):
        self._available_versions = available_versions or {}
        self._raise_error = raise_error

    def list_available_versions(self, unit_name: str) -> List[str]:
        if self._raise_error is not None:
            raise self._raise_error
        return list(self._available_versions.get(unit_name, []))

    def clone_unit(self, unit: SoftwareUnitVersion, dest_dir: Path) -> List[AcquiredFile]:
        raise NotImplementedError("the API never clones — the worker does")

    def scan_cloned_unit(self, unit: SoftwareUnitVersion, clone_path: Path) -> List[AcquiredFile]:
        raise NotImplementedError("the API never scans — the worker does")

    def list_mandatory_files(self, unit_name: str) -> List[str]:
        raise NotImplementedError("the API never acquires files — the worker does")
