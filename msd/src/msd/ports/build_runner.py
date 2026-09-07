"""Port for regenerating a software unit's build-time code (SRS DSM-MSD req 13, 19).

Some DDS/pub-sub units generate their topic manifest and type-support code from
an IDL-like definition at build time — without that step ISourceAnalyzer would
have nothing to scan. The production implementation shells out to gmake
(adapters/source_code/gmake_build_runner.py); tests inject a fake.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class IBuildRunner(ABC):
    """Runs a unit's code-regeneration build before source analysis."""

    @abstractmethod
    def ensure_available(self) -> None:
        """Raise RuntimeError if the build tool is not available. Called once
        up-front when build execution is requested, before any unit is built."""

    @abstractmethod
    def regenerate_code(self, unit_dir: Path) -> None:
        """Run the unit's code-regeneration build if it has a valid build file.

        Best-effort by contract: a missing build file is a no-op, and a build's
        own non-zero exit, a timeout, or a missing build tool are logged but not
        raised — analysis proceeds over whatever code is present."""
