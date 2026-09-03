"""Filesystem-backed catalog of produced Model Setup Data files
(SRS DSM-VAE req 5).

The workspace layout is the index: RunWorkflow writes every run to
`<workspace>/<project>/<platform>/<version>/<run_id>/model_setup_data.json`,
so the files for one selection are exactly the children of that selection's
directory and listing them is one glob. Each file is self-describing — the
summary shown in a listing is read back out of the file's own header — so
there is no separate record to keep in step with the disk.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import List, Optional

from msd.domain.model_setup_data_record import ModelSetupDataRecord
from msd.ports.model_setup_data_catalog import IModelSetupDataCatalog
from msd.services.run_workflow import MSD_JSON_FILE_NAME, run_dir_under, selection_dir_under

logger = logging.getLogger(__name__)


def _candidate_of(payload: dict) -> Optional[dict]:
    """The candidate unit version a run was evaluating, read back out of the
    inventory it recorded (SRS DSM-MSD req 11), or None if it was a run of the
    versions the system version defines.

    Read from the inventory rather than stored separately, for the same reason
    the rest of the record is: the file is the source of truth. Anything
    unexpected in that inventory yields None — a listing must not turn on the
    shape of one field."""
    units = (payload.get("inventory") or {}).get("units")
    if not isinstance(units, list):
        return None
    for unit in units:
        if isinstance(unit, dict) and unit.get("is_candidate"):
            return {"unit_name": unit.get("unit_name"), "version": unit.get("version")}
    return None


class FilesystemModelSetupDataCatalog(IModelSetupDataCatalog):
    """Reads produced Model Setup Data files out of the msd workspace."""

    def __init__(self, workspace: Path):
        self._workspace = Path(workspace)

    def list(
        self, project_id: str, platform_id: str, version_id: str
    ) -> List[ModelSetupDataRecord]:
        selection_dir = selection_dir_under(self._workspace, project_id, platform_id, version_id)
        if not selection_dir.is_dir():
            return []

        records = []
        for run_dir in sorted(selection_dir.iterdir()):
            path = run_dir / MSD_JSON_FILE_NAME
            if not path.is_file():
                continue
            record = self._read_record(path, project_id, platform_id, version_id, run_dir.name)
            if record is not None:
                records.append(record)

        # Newest first. A file with an unreadable timestamp sorts last rather
        # than dropping out of the listing.
        records.sort(key=lambda r: r.generated_at or "", reverse=True)
        return records

    def resolve(
        self, project_id: str, platform_id: str, version_id: str, run_id: str
    ) -> Optional[Path]:
        # run_dir_under sanitizes every component, but that is not a boundary:
        # the sanitizer replaces '/' yet keeps '.', so ".." survives it and
        # each component can climb one level. All four arrive from URL path
        # segments, and together they climb out of the workspace — so the
        # containment check below, not the sanitizing, is what holds the line.
        run_dir = run_dir_under(self._workspace, project_id, platform_id, version_id, run_id)
        path = (run_dir / MSD_JSON_FILE_NAME).resolve()
        if not self._contains(path):
            logger.warning("catalog: rejected run id %r — resolves outside the workspace", run_id)
            return None
        return path if path.is_file() else None

    def _contains(self, path: Path) -> bool:
        """Is `path` inside the workspace? os.path.commonpath rather than
        Path.is_relative_to, which needs Python 3.9 (this package targets 3.8)."""
        root = str(self._workspace.resolve())
        try:
            return os.path.commonpath([root, str(path)]) == root
        except ValueError:
            # Raised for paths on different drives (Windows) — not contained.
            return False

    def _read_record(
        self, path: Path, project_id: str, platform_id: str, version_id: str, run_id: str
    ) -> Optional[ModelSetupDataRecord]:
        """One listing entry read from the file's header, or None if the file
        cannot serve as one. A bad file is skipped with a warning rather than
        failing the whole listing: the workspace can hold artifacts from older
        runs whose shape predates the current envelope, and one of those must
        not cost the user the rest of their files."""
        try:
            with path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError) as exc:
            logger.warning("catalog: skipping unreadable %s: %s", path, exc)
            return None
        if not isinstance(payload, dict) or "generated_at" not in payload:
            logger.warning("catalog: skipping %s — not a Model Setup Data file", path)
            return None
        return ModelSetupDataRecord(
            run_id=run_id,
            project_id=project_id,
            platform_id=platform_id,
            version_id=version_id,
            path=path,
            generated_at=payload.get("generated_at"),
            produced_by=payload.get("produced_by"),
            scale=(payload.get("graph") or {}).get("metadata", {}).get("scale", {}),
            candidate=_candidate_of(payload),
        )
