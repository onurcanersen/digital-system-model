"""The final Model Setup Data artifact (SRS DSM-MSD req 19)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from domain.acquired_file import AcquiredFile
from domain.inventory import SoftwareUnitVersionInventory
from domain.project_context import ProjectContext
from domain.validation import ValidationError


@dataclass(frozen=True)
class ModelSetupDataTopic:
    """A topic with its QoS properties — one node of the Model Setup Data graph
    (SRS DSM-MSD req 19). Equality and hash are by name, so topic sets
    deduplicate by name."""
    name: str
    size: Optional[int] = None
    durability: Optional[str] = None
    reliability: Optional[str] = None
    transport_priority: Optional[str] = None

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ModelSetupDataTopic):
            return self.name == other.name
        return False


@dataclass
class ModelSetupData:
    """The verified, traceable data package handed off to model construction (req 1, 19).

    `graph` carries the node-relationship-shaped payload (nodes, topics,
    applications, libraries, relationships) built by JsonModelSetupDataWriter —
    the structural input the model construction process consumes (SRS DSM-CSM
    req 2: accept the Model Setup Data produced by the Model Setup Data
    Generation component).
    """
    context: ProjectContext
    inventory: SoftwareUnitVersionInventory
    acquired_files: List[AcquiredFile]
    graph: Dict[str, Any]
    validation_errors: List[ValidationError] = field(default_factory=list)
    generated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "context": self.context.to_dict(),
            "inventory": self.inventory.to_dict(),
            "acquired_files": [f.to_dict() for f in self.acquired_files],
            "validation_errors": [e.to_dict() for e in self.validation_errors],
            "generated_at": self.generated_at.isoformat(),
            "graph": self.graph,
        }
