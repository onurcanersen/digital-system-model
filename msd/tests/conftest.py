"""Bootstraps tests/ itself onto sys.path so `fakes.*` resolves via bare
imports. msd itself resolves via the editable install (`pip install -e ./msd`)."""

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_TESTS_DIR))
