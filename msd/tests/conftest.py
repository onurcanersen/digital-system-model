"""Bootstraps src/ (so api/use_cases/model/ports/adapters import as plain
top-level packages) and tests/ itself (so `fakes.*` resolves) onto sys.path."""

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_TESTS_DIR.parent / "src"))
sys.path.insert(0, str(_TESTS_DIR))
