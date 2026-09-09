"""Build runner: finds a Java-buildable Makefile and runs `gmake
regenerate_code` (supports SRS DSM-MSD req 13, 19). Some DDS/pub-sub units
generate their topic manifest and type-support code from an IDL-like
definition at build time — if that hasn't run yet, ISourceAnalyzer would
have nothing to scan.

The `run_regenerate_code` function is a pure helper; `find_valid_makefile`
comes from mandatory_file_catalog.py, where it is shared with the scan.
`GmakeBuildRunner` is the IBuildRunner adapter that combines them for
AnalyzeSoftwareUnits.

A build's own non-zero exit code is intentionally NOT treated as failure —
only a timeout, a missing `gmake`, or an unexpected exception are.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import List, Tuple

from msd.adapters.source_code.mandatory_file_catalog import find_valid_makefile
from msd.ports.build_runner import IBuildRunner

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 300


def check_gmake_available() -> bool:
    """Return True if the `gmake` binary is available on the system."""
    try:
        result = subprocess.run(["gmake", "--version"], capture_output=True, text=True)
        return result.returncode == 0
    except (FileNotFoundError, OSError):
        return False


def run_regenerate_code(makefile_path: Path, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> Tuple[bool, str]:
    """Run `gmake regenerate_code` in the directory containing `makefile_path`.

    Returns (True, output) even if gmake's own exit code is non-zero — only
    a timeout, a missing `gmake`, or an unexpected exception return False.
    """
    makefile_dir = makefile_path.parent
    try:
        result = subprocess.run(
            ["gmake", "regenerate_code"],
            cwd=makefile_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        logger.info("gmake regenerate_code completed in %s (exit code: %s)", makefile_dir, result.returncode)
        return True, result.stdout or result.stderr or ""
    except subprocess.TimeoutExpired:
        message = f"Command timed out after {timeout} seconds"
        logger.error("%s in %s", message, makefile_dir)
        return False, message
    except FileNotFoundError:
        message = "gmake command not found. Please ensure it is installed."
        logger.error(message)
        return False, message
    except OSError as exc:
        message = f"Unexpected error: {exc}"
        logger.error("%s in %s", message, makefile_dir)
        return False, message


class GmakeBuildRunner(IBuildRunner):
    """IBuildRunner backed by `gmake regenerate_code` (config.ini's
    makefile_include_patterns decide which Makefiles count as valid)."""

    def __init__(self, makefile_include_patterns: List[str]):
        self._patterns = makefile_include_patterns

    def ensure_available(self) -> None:
        if not check_gmake_available():
            raise RuntimeError("gmake is not available but build execution was requested")

    def regenerate_code(self, unit_dir: Path) -> None:
        makefile_path = find_valid_makefile(unit_dir, self._patterns)
        if makefile_path is None:
            return
        logger.info("gmake: running regenerate_code for %s (%s)", unit_dir, makefile_path)
        run_regenerate_code(makefile_path)
