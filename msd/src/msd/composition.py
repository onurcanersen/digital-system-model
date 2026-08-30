"""Composition root: `load_components()` takes the caller-supplied config-mgmt
DB and source code repository adapters (msd no longer owns that connection
info — see msd/config.py) and hands back the state a caller needs to run
the clone + generate workflow. `Components` keeps the workflow steps
(cloning, generating, combined run) as separate, stateless use-case
factories.

msd is a library with no API or worker of its own — vae's Flask API and
Celery worker (see the vae package) are the callers that build the
config-mgmt/source-repo adapters from user-supplied credentials, build a
per-run workspace dir keyed by a task id, and invoke RunWorkflow, so
concurrent runs never collide and runs never reuse previous artifacts
(see services/run_workflow.py for the orchestration itself).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from msd.adapters.analysis.manual_source_analyzer import ManualSourceAnalyzer
from msd.adapters.json_model_setup_data_writer import JsonModelSetupDataWriter
from msd.adapters.source_code.make_build_runner import MakeBuildRunner
from msd.config import Config, get_config
from msd.domain.validation import MandatoryFieldRule
from msd.ports.config_management_repository import IConfigManagementRepository
from msd.ports.source_code_repository import ISourceCodeRepository
from msd.services.acquire_project_context import AcquireProjectContext
from msd.services.analyze_software_units import AnalyzeSoftwareUnits
from msd.services.build_software_unit_inventory import BuildSoftwareUnitInventory
from msd.services.clone_software_units import CloneSoftwareUnits
from msd.services.generate_model_setup_data import GenerateModelSetupData
from msd.services.run_workflow import RunWorkflow
from msd.services.validate_mandatory_fields import ValidateMandatoryFields

MSD_ROOT = Path(__file__).resolve().parents[0]

_VALIDATION_RULES = [
    MandatoryFieldRule("file_name", "AcquiredFile"),
    MandatoryFieldRule("name", "ExtractedTopic"),
]


@dataclass
class Components:
    config_repo: IConfigManagementRepository
    source_repo: ISourceCodeRepository
    workspace: Path

    def clone(self) -> CloneSoftwareUnits:
        return CloneSoftwareUnits(
            project_context=AcquireProjectContext(self.config_repo),
            inventory=BuildSoftwareUnitInventory(self.config_repo),
            source_repo=self.source_repo,
        )

    def generate(self, selection_dir: Path) -> GenerateModelSetupData:
        config = get_config()
        return GenerateModelSetupData(
            project_context=AcquireProjectContext(self.config_repo),
            inventory=BuildSoftwareUnitInventory(self.config_repo),
            source_repo=self.source_repo,
            analyze=AnalyzeSoftwareUnits(
                ManualSourceAnalyzer(config.analyzer),
                MakeBuildRunner(config.analyzer.makefile_include_patterns),
                run_build=config.analyzer.run_build,
            ),
            validate=ValidateMandatoryFields(list(_VALIDATION_RULES)),
            writer=JsonModelSetupDataWriter(selection_dir),
            config_repo=self.config_repo,
        )

    def workflow(self) -> RunWorkflow:
        return RunWorkflow(clone=self.clone(), generate_factory=self.generate)


def _workspace_root(config: Config) -> Path:
    path = Path(config.workspace.path)
    return path if path.is_absolute() else MSD_ROOT / path


def load_components(
    config_repo: IConfigManagementRepository,
    source_repo: ISourceCodeRepository,
    workspace: Optional[Path] = None,
) -> Components:
    config = get_config()
    root = workspace or _workspace_root(config)
    return Components(config_repo=config_repo, source_repo=source_repo, workspace=root)
