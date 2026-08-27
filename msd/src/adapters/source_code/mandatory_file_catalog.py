"""Mandatory-file lookup for the source code repository (SRS DSM-MSD req 15):
the per-unit mandatory file manifest behind the missing-file status.

The list is formula-driven (not a curated per-unit-type catalog) — but the
topic manifest path is parameterized by unit_name, since the
"src/<folder_name>.xml" convention (see manual_source_analyzer.py) means
that path genuinely differs per unit.

Also the canonical home for "what counts as a valid Makefile" — both
git_source_code_repository.py (req 15's existence+content check) and
build_runner.py (deciding whether to run gmake regenerate_code) need it.
"""

from __future__ import annotations

import re
from typing import List

MAKEFILE_RELATIVE_PATH = "Makefile"

_MAKEFILE_COMMENT_PATTERN = re.compile(r"#.*$", re.MULTILINE)


def get_mandatory_files(unit_name: str) -> List[str]:
    """Return the file paths (relative to the unit's repo root) that are
    mandatory to obtain for `unit_name`."""
    return [MAKEFILE_RELATIVE_PATH, f"src/{unit_name}.xml"]


def makefile_has_valid_include(content: str, patterns: List[str]) -> bool:
    """Return True if `content` contains one of `patterns` outside of comments.

    An empty `patterns` list yields False (any([]) is False) — no configured
    pattern means nothing can satisfy the check.
    """
    active_content = _MAKEFILE_COMMENT_PATTERN.sub("", content)
    return any(pattern in active_content for pattern in patterns)
