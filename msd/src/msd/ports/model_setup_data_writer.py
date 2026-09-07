"""Port for building and writing the final Model Setup Data artifact
(SRS DSM-MSD req 19)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List

from msd.domain.inventory import SoftwareUnitVersionInventory
from msd.domain.model_setup_data import ModelSetupData
from msd.domain.project_context import ProjectContext
from msd.domain.extracted_topic import ExtractedTopic
from msd.ports.config_management_repository import IConfigManagementRepository


class IModelSetupDataWriter(ABC):
    """Port for building and writing the final Model Setup Data artifact (SRS DSM-MSD req 19)."""

    @abstractmethod
    def build_graph(
        self,
        context: ProjectContext,
        inventory: SoftwareUnitVersionInventory,
        extracted_topics: List[ExtractedTopic],
        config_repo: IConfigManagementRepository,
    ) -> Dict[str, Any]:
        """Build the node-relationship-shaped graph payload (nodes, topics,
        applications, libraries, relationships) for the acquired data."""

    @abstractmethod
    def write(self, data: ModelSetupData, output_path: Path) -> Path:
        """Save `data` as the Model Setup Data file and return its path."""
