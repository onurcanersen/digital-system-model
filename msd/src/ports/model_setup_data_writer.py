"""Port for writing the final Model Setup Data artifact (SRS DSM-MSD req 19)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from model.model_setup_data import ModelSetupData


@runtime_checkable
class IModelSetupDataWriter(Protocol):
    """Structural port — no explicit inheritance required of adapters."""

    def write(self, data: ModelSetupData, output_path: Path) -> Path:
        """Save `data` as the Model Setup Data file and return its path."""
        ...
