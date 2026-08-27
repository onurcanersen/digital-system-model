"""Port for topic/dependency extraction from a software unit's cloned tree
(SRS DSM-MSD req 13, 19). CodeQL-based analysis is intentionally not
supported; only the manual XML/import strategy
(adapters/analysis/manual_source_analyzer.py) is.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from model.extracted_topic import ExtractedTopic


class ISourceAnalyzer(ABC):
    """Abstract base for topic extraction strategies (req 19)."""

    @abstractmethod
    def extract(self, folder_path: Path, folder_name: str) -> List[ExtractedTopic]:
        """Extract the unit's pub/sub/uses topics as ExtractedTopic records."""
