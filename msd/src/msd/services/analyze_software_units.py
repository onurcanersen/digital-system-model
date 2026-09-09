"""Use case: extract topic pub/sub/uses entries from each cloned unit.

Supports req 19 (populating the Model Setup Data artifact); not itself an
SRS-numbered requirement.

Optionally runs the unit's code-regeneration build (IBuildRunner) before
extraction — some DDS/pub-sub units generate their topic manifest/type-support
code from an IDL-like definition at build time, so without this the analyzer
could have nothing to scan. Opt-in via `run_build` (conservative default: off
unless explicitly requested).

The per-unit build + extraction runs up to UNIT_CONCURRENCY units at once
(see services/concurrency.py) — up to that many concurrent
`gmake regenerate_code` builds — and the extracted entries come back in
inventory order.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, List, Optional

from msd.domain.inventory import SoftwareUnitVersion, SoftwareUnitVersionInventory
from msd.domain.extracted_topic import ExtractedTopic, expand_pubsub_entries
from msd.ports.build_runner import IBuildRunner
from msd.ports.source_analyzer import ISourceAnalyzer
from msd.services.concurrency import run_units_concurrently
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

        units = inventory.units
        # The extracted entries are flattened back into inventory order below,
        # so the run's artifact is unaffected by which unit finished first.
        topics_per_unit = run_units_concurrently(
            units, lambda unit: self._analyze_one(unit, dest_root), PHASE_ANALYZE, progress
        )
        entries: List[ExtractedTopic] = [
            entry for unit_topics in topics_per_unit for entry in unit_topics
        ]
        return expand_pubsub_entries(entries)

    def _analyze_one(self, unit: SoftwareUnitVersion, dest_root: Path) -> List[ExtractedTopic]:
        """The per-unit analyze: the optional code-regeneration build first
        (units that generate their manifest at build time), then the topic
        extraction over the result."""
        folder_path = dest_root / unit.unit_name
        if self._run_build:
            self._build_runner.regenerate_code(folder_path)
        logger.info("analyze: extracting topics from %s %s", unit.unit_name, unit.version)
        return self._analyzer.extract(folder_path, unit.unit_name)
