"""A catalog entry describing one produced Model Setup Data file, without
carrying the file itself (SRS DSM-VAE req 5: list the Model Setup Data files
belonging to the selected project, platform and system version).

This is the summary a listing needs — who produced the file, when, at what
scale, and the identity to fetch it by — read back from the file's own header
by the catalog adapter. The file remains the source of truth; nothing here is
stored separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ModelSetupDataRecord:
    """One produced model_setup_data.json, identified by its selection plus the
    id of the run that produced it.

    `produced_by` is None for a file produced without a named user, and
    `generated_at` is the ISO-8601 string as the file records it — kept as
    written rather than parsed, so a file whose timestamp is unreadable still
    lists (see FilesystemModelSetupDataCatalog).

    `candidate` is the {"unit_name", "version"} the run was evaluating (SRS
    DSM-MSD req 11), or None for a run of the versions the system version
    defines. It is what distinguishes otherwise identical files in a listing:
    several runs of one selection differ only by the candidate they carried.
    """
    run_id: str
    project_id: str
    platform_id: str
    version_id: str
    path: Path
    generated_at: Optional[str] = None
    produced_by: Optional[str] = None
    scale: Optional[Dict[str, int]] = None
    candidate: Optional[Dict[str, str]] = None

    def to_dict(self) -> Dict[str, Any]:
        """The listing payload. `path` is deliberately left out: it is a
        server-side filesystem location, and callers address a file by its
        (project, platform, version, run_id) identity instead."""
        return {
            "run_id": self.run_id,
            "project_id": self.project_id,
            "platform_id": self.platform_id,
            "version_id": self.version_id,
            "generated_at": self.generated_at,
            "produced_by": self.produced_by,
            "scale": self.scale or {},
            "candidate": self.candidate,
        }
