"""Port for finding Model Setup Data files that earlier runs produced
(SRS DSM-VAE req 5).

The read side of the artifact store, kept separate from IModelSetupDataWriter:
that port builds and saves one run's file and has no business enumerating
anyone else's. A catalog addresses a file by its selection plus the id of the
run that produced it — an identity that outlives the task-tracking backend, so
a file stays reachable long after its run's execution record has expired.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional

from msd.domain.model_setup_data_record import ModelSetupDataRecord


class IModelSetupDataCatalog(ABC):
    """Port for listing and locating produced Model Setup Data files (req 5)."""

    @abstractmethod
    def list(
        self, project_id: str, platform_id: str, version_id: str
    ) -> List[ModelSetupDataRecord]:
        """Every Model Setup Data file produced for this selection, newest
        first. Returns an empty list when the selection has produced none —
        an unknown selection is not an error, it simply has no files."""

    @abstractmethod
    def resolve(
        self, project_id: str, platform_id: str, version_id: str, run_id: str
    ) -> Optional[Path]:
        """The path of one produced file, or None when no such file exists.
        Implementations must treat `run_id` as untrusted input."""
