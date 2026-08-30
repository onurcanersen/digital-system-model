"""Port for the source code and installation-script repository (SRS DSM-MSD req 2.2, 13-16)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from msd.domain.acquired_file import AcquiredFile
from msd.domain.inventory import SoftwareUnitVersion


class SourceRepoAccessError(Exception):
    """Raised when the source repository cannot be accessed (req 16)."""


class SourceRepoAuthError(Exception):
    """Raised on an authorization error obtaining files (req 16)."""


class SourceRepoIntegrityError(Exception):
    """Raised on an integrity error in obtained files (req 16)."""


class ISourceCodeRepository(ABC):
    """Port for the software units and installation-scripts source code repository."""

    @abstractmethod
    def clone_unit(self, unit: SoftwareUnitVersion, dest_dir: Path) -> List[AcquiredFile]:
        """Access and transfer the source code, installation scripts, and
        configuration files for `unit` into `dest_dir` (req 13).

        Clones the full repository (needed by ISourceAnalyzer to extract
        topics/dependencies) but returns AcquiredFile records only for the
        files matched against `list_mandatory_files`, per req 14 — keeps the
        returned list bounded regardless of real repo size.

        Raises SourceRepoAccessError/SourceRepoAuthError/SourceRepoIntegrityError
        on the respective failure (req 16).
        """

    @abstractmethod
    def scan_cloned_unit(self, unit: SoftwareUnitVersion, clone_path: Path) -> List[AcquiredFile]:
        """Collect AcquiredFile records for the mandatory files present under an
        already-cloned unit directory at `clone_path` — no network access.
        The generate step reuses previously cloned repositories via this method
        instead of re-cloning."""

    @abstractmethod
    def list_mandatory_files(self, unit_name: str) -> List[str]:
        """Return the file names that are mandatory to obtain for `unit_name` (req 15)."""
