"""Bootstraps the msd/ root (so domain/services/ports/adapters and app import as plain
top-level packages) and tests/ itself (so `fakes.*` resolves) onto sys.path."""

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_TESTS_DIR.parent))
sys.path.insert(0, str(_TESTS_DIR))
