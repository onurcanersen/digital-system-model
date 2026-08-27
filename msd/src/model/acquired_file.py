"""Files obtained from the source code repository (SRS DSM-MSD req 13-16)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List

from model.status import AcquisitionStatus


@dataclass
class FileAccessError:
    """An access, authorization, or integrity error on one repo file (req 16)."""
    file_path: str
    error_type: str  # "access" | "authorization" | "integrity"
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {"file_path": self.file_path, "error_type": self.error_type, "message": self.message}


@dataclass
class AcquiredFile:
    """One mandatory file obtained from the source code repository (req 13-14).

    Only mandatory/manifest files (per ISourceCodeRepository.list_mandatory_files)
    get a record here — the full repository is still cloned to disk for analysis,
    but recording every file in the tree would make this list unbounded for real
    (non-fixture) source units.
    """
    unit_name: str
    file_name: str
    file_path: str
    package_version: str
    updated_at: datetime
    status: AcquisitionStatus = AcquisitionStatus.OK
    errors: List[FileAccessError] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "unit_name": self.unit_name,
            "file_name": self.file_name,
            "file_path": self.file_path,
            "package_version": self.package_version,
            "updated_at": self.updated_at.isoformat(),
            "status": self.status.value,
            "errors": [e.to_dict() for e in self.errors],
        }
