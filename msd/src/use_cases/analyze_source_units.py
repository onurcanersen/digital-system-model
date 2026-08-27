"""Use case: extract topic pub/sub/uses entries from each cloned unit.

Supports req 19 (populating the Model Setup Data artifact); not itself an
SRS-numbered requirement.

Optionally runs `gmake regenerate_code` before extraction — some DDS/pub-sub
units generate their topic manifest/type-support code from an IDL-like
definition at build time, so without this the analyzer could have nothing
to scan. Opt-in via `run_build` (conservative default: off unless explicitly
requested). `build_runner` is called directly (module functions, not a
stateful port) — the same adapter-to-adapter precedent already used for
SystemRepoParser/TypeSupportParser in json_model_setup_data_writer.py.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

from adapters.source_code.build_runner import check_gmake_available, find_valid_makefile, run_regenerate_code
from model.inventory import SoftwareUnitVersionInventory
from model.topic_entry import TopicEntry, expand_pubsub_entries
from ports.source_analyzer import ISourceAnalyzer

logger = logging.getLogger(__name__)


class AnalyzeSourceUnitsUseCase:
    """Runs the configured ISourceAnalyzer over every cloned unit in the inventory."""

    def __init__(self, analyzer: ISourceAnalyzer, run_build: bool = False):
        self._analyzer = analyzer
        self._run_build = run_build

    def execute(self, inventory: SoftwareUnitVersionInventory, dest_root: Path) -> List[TopicEntry]:
        if self._run_build and not check_gmake_available():
            raise RuntimeError("gmake is not available but build execution was requested")

        entries: List[TopicEntry] = []
        for unit in inventory.units:
            folder_path = dest_root / unit.unit_name
            if self._run_build:
                self._maybe_build(unit.unit_name, folder_path)
            logger.info("analyze: extracting topics from %s %s", unit.unit_name, unit.version)
            entries.extend(self._analyzer.extract(folder_path, unit.unit_name))
        return expand_pubsub_entries(entries)

    @staticmethod
    def _maybe_build(unit_name: str, folder_path: Path) -> None:
        makefile_path = find_valid_makefile(folder_path)
        if makefile_path is None:
            return
        logger.info("analyze: running gmake regenerate_code for %s (%s)", unit_name, makefile_path)
        run_regenerate_code(makefile_path)
