"""Composition root: `load_components()` reads config.ini, builds the real
adapters for the config-mgmt DB and the source code repository, and hands
back the state both the Flask API (api.py) and the Celery worker
(worker.py) need. `Components` keeps the workflow steps (cloning,
generating, combined run) as separate, stateless use-case factories.

The worker runs the RunWorkflow in a workspace dir keyed by the task's id,
so concurrent runs never collide and runs never reuse previous artifacts
(see services/run_workflow.py for the orchestration itself).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from adapters.analysis.manual_source_analyzer import ManualSourceAnalyzer
from adapters.json_model_setup_data_writer import JsonModelSetupDataWriter
from adapters.mysql_config_management_repository import MysqlConfigManagementRepository
from adapters.source_code.git_source_code_repository import GitSourceCodeRepository
from adapters.source_code.make_build_runner import MakeBuildRunner
from config import DEFAULT_CONFIG_PATH, Config, get_config
from domain.data_source import SourceType
from domain.validation import MandatoryFieldRule
from ports.config_management_repository import IConfigManagementRepository
from ports.source_code_repository import ISourceCodeRepository
from services.acquire_project_context import AcquireProjectContext
from services.analyze_software_units import AnalyzeSoftwareUnits
from services.build_software_unit_inventory import BuildSoftwareUnitInventory
from services.clone_software_units import CloneSoftwareUnits
from services.generate_model_setup_data import GenerateModelSetupData
from services.run_workflow import RunWorkflow
from services.validate_mandatory_fields import ValidateMandatoryFields

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
    workspace: Optional[Path] = None,
) -> Components:
    config = get_config()

    config_mgmt = next((c for c in config.data_sources if c.source_type == SourceType.CONFIG_MGMT_DB), None)
    source_repo_cfg = next((c for c in config.data_sources if c.source_type == SourceType.SOURCE_CODE_REPO), None)
    if config_mgmt is None:
        raise RuntimeError(f"no config_mgmt_db data source configured in {DEFAULT_CONFIG_PATH}")
    if source_repo_cfg is None:
        raise RuntimeError(f"no source_code_repo data source configured in {DEFAULT_CONFIG_PATH}")

    root = workspace or _workspace_root(config)
    return Components(
        config_repo=MysqlConfigManagementRepository.from_data_source_config(config_mgmt),
        source_repo=GitSourceCodeRepository.from_data_source_config(
            source_repo_cfg, config.analyzer.makefile_include_patterns
        ),
        workspace=root,
    )
