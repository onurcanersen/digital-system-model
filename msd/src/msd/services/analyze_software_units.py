"""Use case: extract topic pub/sub/uses entries from each cloned unit.

Supports req 19 (populating the Model Setup Data artifact); not itself an
SRS-numbered requirement.

Optionally runs the unit's code-regeneration build (IBuildRunner) before
extraction — some DDS/pub-sub units generate their topic manifest/type-support
code from an IDL-like definition at build time, so without this the analyzer
could have nothing to scan. Opt-in via `run_build` (conservative default: off
unless explicitly requested).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, List, Optional

from msd.domain.inventory import SoftwareUnitVersionInventory
from msd.domain.extracted_topic import ExtractedTopic, expand_pubsub_entries
from msd.ports.build_runner import IBuildRunner
from msd.ports.source_analyzer import ISourceAnalyzer
from msd.services.progress import PHASE_ANALYZE

logger = logging.getLogger(__name__)


class AnalyzeSoftwareUnits:
    """Runs the configured ISourceAnalyzer over every cloned unit in the inventory."""

    def __init__(self, analyzer: ISourceAnalyzer, build_runner: IBuildRunner, run_build: bool = False):
        self._analyzer = analyzer
        self._build_runner = build_runner
        self._run_build = run_build

    def execute(
        self,
        inventory: SoftwareUnitVersionInventory,
        dest_root: Path,
        progress: Optional[Callable[[str, int, int], None]] = None,
    ) -> List[ExtractedTopic]:
        if self._run_build:
            self._build_runner.ensure_available()

        total = len(inventory.units)
        report = progress or (lambda *_: None)
        report(PHASE_ANALYZE, 0, total)
        entries: List[ExtractedTopic] = []
        for index, unit in enumerate(inventory.units):
            folder_path = dest_root / unit.unit_name
            if self._run_build:
                self._build_runner.regenerate_code(folder_path)
            logger.info("analyze: extracting topics from %s %s", unit.unit_name, unit.version)
            entries.extend(self._analyzer.extract(folder_path, unit.unit_name))
            report(PHASE_ANALYZE, index + 1, total)
        return expand_pubsub_entries(entries)
