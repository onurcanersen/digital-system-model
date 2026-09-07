"""Use case: run the combined clone → generate MSD workflow for one selection
(SRS DSM-MSD req 5, 13, 19).

One run = one isolated run directory: all artifacts (cloned unit repositories
and model_setup_data.json) live under
`<workspace>/<project>/<platform>/<version>/<run_id>`, so concurrent runs
never collide and runs never reuse previous artifacts. The run id is the
*innermost* segment on purpose: every run for one selection is then a direct
child of that selection's directory, so listing the Model Setup Data files
produced for a project/platform/version is a single directory read (SRS
DSM-VAE req 5, served by adapters/filesystem_model_setup_data_catalog.py).

Per-unit failures are recorded in the result payload; context-level failures
(config DB unreachable, platform not found) propagate as RuntimeError from
the clone/generate use cases' own context acquisition and fail the run.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from msd.domain.inventory import CandidateUnitVersion
from msd.domain.model_setup_data import ModelSetupData
from msd.domain.status import AcquisitionStatus, GenerateUnitStatus
from msd.domain.validation import ValidationError
from msd.services.clone_software_units import CloneSoftwareUnits, CloneUnitResult
from msd.services.generate_model_setup_data import GenerateModelSetupData

logger = logging.getLogger(__name__)

MSD_JSON_FILE_NAME = "model_setup_data.json"


def _sanitize(path_component: str) -> str:
    """Make a DB-provided id safe to use as a directory name."""
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", path_component)
    return sanitized or "_"


def selection_dir_under(root: Path, project_id: str, platform_id: str, version_id: str) -> Path:
    """<root>/<project>/<platform>/<version> with sanitized id components — the
    directory holding every run produced for one selection."""
    return (
        root
        / _sanitize(project_id)
        / _sanitize(platform_id)
        / _sanitize(version_id)
    )


def run_dir_under(
    workspace: Path, project_id: str, platform_id: str, version_id: str, run_id: str
) -> Path:
    """<workspace>/<project>/<platform>/<version>/<run_id> — one run's private
    directory, holding its cloned unit repositories and its
    model_setup_data.json. The run id goes last so all runs for a selection sit
    side by side under `selection_dir_under(...)`."""
    return selection_dir_under(workspace, project_id, platform_id, version_id) / _sanitize(run_id)


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
    run_id: str
    run_dir: Path
    output_path: Path
    clone_results: List[CloneUnitResult]
    unit_summaries: List[dict]
    validation_errors: List[ValidationError]
    scale: Dict[str, int]
    candidate: Optional[CandidateUnitVersion] = None

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "output_path": str(self.output_path),
            "clone": {"units": [r.to_dict() for r in self.clone_results]},
            "units": self.unit_summaries,
            "validation_errors": [e.to_dict() for e in self.validation_errors],
            "scale": self.scale,
            # None for a run of the versions the system version pins; the unit
            # under evaluation otherwise (req 11), so the run's outcome says
            # what it was a run *of*.
            "candidate": self.candidate.to_dict() if self.candidate else None,
        }


class RunWorkflow:
    """Runs cloning, then MSD-JSON generation, for one selection inside
    the run-private run dir (req 13, 19)."""

    def __init__(
        self,
        clone: CloneSoftwareUnits,
        generate_factory: Callable[[Path], GenerateModelSetupData],
    ):
        self._clone = clone
        self._generate_factory = generate_factory

    def execute(
        self,
        workspace: Path,
        project_id: str,
        platform_id: str,
        version_id: str,
        run_id: str,
        produced_by: Optional[str] = None,
        candidate: Optional[CandidateUnitVersion] = None,
    ) -> WorkflowResult:
        run_dir = run_dir_under(workspace, project_id, platform_id, version_id, run_id)
        output_path = run_dir / MSD_JSON_FILE_NAME
        logger.info("workflow: clone+generate for %s/%s/%s into %s",
                    project_id, platform_id, version_id, run_dir)
        if candidate is not None:
            logger.info("workflow: evaluating candidate %s %s in place of the version this system version defines",
                        candidate.unit_name, candidate.version)

        # Both steps get the same candidate: each builds its own inventory, and
        # they must agree on which version was acquired (req 11). The run dir is
        # keyed by run id, so a candidate run never reuses a previous run's clones.
        clone_results = self._clone.execute(
            run_dir,
            project_id=project_id,
            platform_id=platform_id,
            version_id=version_id,
            candidate=candidate,
        )

        # The generate step (and the writer/parsers it builds) is handed the
        # same dir the clone step just filled — that coupling is what the mock
        # enrichment parsers rely on, and it is unaffected by where that dir
        # sits in the workspace.
        data = self._generate_factory(run_dir).execute(
            run_dir,
            output_path,
            project_id=project_id,
            platform_id=platform_id,
            version_id=version_id,
            produced_by=produced_by,
            candidate=candidate,
        )

        return WorkflowResult(
            run_id=run_id,
            run_dir=run_dir,
            output_path=output_path,
            clone_results=clone_results,
            unit_summaries=generate_unit_summary(data, run_dir),
            validation_errors=data.validation_errors,
            scale=data.graph.get("metadata", {}).get("scale", {}),
            candidate=candidate,
        )
