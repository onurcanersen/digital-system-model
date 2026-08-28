"""Use case: run the combined clone → generate MSD workflow for one selection
(SRS DSM-MSD req 5, 13, 19).

One run = one isolated workspace directory: all artifacts (cloned unit
repositories and model_setup_data.json) live under
`run_root/<project>/<platform>/<version>`, so concurrent runs never collide
and runs never reuse previous artifacts. Per-unit failures are recorded in
the result payload; context-level failures (config DB unreachable, platform
not found) propagate as RuntimeError from the clone/generate use cases' own
context acquisition and fail the run.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List

from domain.model_setup_data import ModelSetupData
from domain.status import AcquisitionStatus, GenerateUnitStatus
from domain.validation import ValidationError
from services.clone_software_units import CloneSoftwareUnits, CloneUnitResult
from services.generate_model_setup_data import GenerateModelSetupData

logger = logging.getLogger(__name__)

MSD_JSON_FILE_NAME = "model_setup_data.json"


def _sanitize(path_component: str) -> str:
    """Make a DB-provided id safe to use as a directory name."""
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", path_component)
    return sanitized or "_"


def selection_dir_under(root: Path, project_id: str, platform_id: str, version_id: str) -> Path:
    """<root>/<project>/<platform>/<version> with sanitized id components.
    A per-run root (e.g. <workspace>/<task_id>) isolates one workflow run's
    artifacts."""
    return (
        root
        / _sanitize(project_id)
        / _sanitize(platform_id)
        / _sanitize(version_id)
    )


def generate_unit_summary(data: ModelSetupData, selection_dir: Path) -> List[dict]:
    """Per-unit generate-stage status: ok / missing_files / error / not_cloned,
    derived from the acquired-file records and the on-disk unit directories."""
    statuses_by_unit: Dict[str, set] = {}
    for record in data.acquired_files:
        statuses_by_unit.setdefault(record.unit_name, set()).add(record.status)
    summary = []
    for unit in data.inventory.units:
        statuses = statuses_by_unit.get(unit.unit_name, set())
        if not (selection_dir / unit.unit_name).is_dir():
            status = GenerateUnitStatus.NOT_CLONED
        elif AcquisitionStatus.MISSING_DATA in statuses:
            status = GenerateUnitStatus.MISSING_FILES
        elif AcquisitionStatus.ERROR in statuses:
            status = GenerateUnitStatus.ERROR
        else:
            status = GenerateUnitStatus.OK
        summary.append({"unit_name": unit.unit_name, "version": unit.version, "status": status.value})
    return summary


@dataclass
class WorkflowResult:
    """The JSON-serializable outcome of one combined clone → generate run."""
    selection_dir: Path
    output_path: Path
    clone_results: List[CloneUnitResult]
    unit_summaries: List[dict]
    validation_errors: List[ValidationError]
    scale: Dict[str, int]

    def to_dict(self) -> dict:
        return {
            "workspace": str(self.selection_dir),
            "output_path": str(self.output_path),
            "clone": {"units": [r.to_dict() for r in self.clone_results]},
            "units": self.unit_summaries,
            "validation_errors": [e.to_dict() for e in self.validation_errors],
            "scale": self.scale,
        }


class RunWorkflow:
    """Runs cloning, then MSD-JSON generation, for one selection inside
    the run-private selection dir (req 13, 19)."""

    def __init__(
        self,
        clone: CloneSoftwareUnits,
        generate_factory: Callable[[Path], GenerateModelSetupData],
    ):
        self._clone = clone
        self._generate_factory = generate_factory

    def execute(
        self,
        run_root: Path,
        project_id: str,
        platform_id: str,
        version_id: str,
    ) -> WorkflowResult:
        selection_dir = selection_dir_under(run_root, project_id, platform_id, version_id)
        output_path = selection_dir / MSD_JSON_FILE_NAME
        logger.info("workflow: clone+generate for %s/%s/%s into %s",
                    project_id, platform_id, version_id, selection_dir)

        clone_results = self._clone.execute(
            selection_dir,
            project_id=project_id,
            platform_id=platform_id,
            version_id=version_id,
        )

        data = self._generate_factory(selection_dir).execute(
            selection_dir,
            output_path,
            project_id=project_id,
            platform_id=platform_id,
            version_id=version_id,
        )

        return WorkflowResult(
            selection_dir=selection_dir,
            output_path=output_path,
            clone_results=clone_results,
            unit_summaries=generate_unit_summary(data, selection_dir),
            validation_errors=data.validation_errors,
            scale=data.graph.get("metadata", {}).get("scale", {}),
        )
