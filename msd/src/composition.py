"""Composition of msd's components from the saved data-source configs
(SRS DSM-MSD req 4), wiring the use cases that implement the cloning and
generation workflow (req 5, 13, 19).

`load_components()` reads msd.ini (req 4), builds the real adapters for the
config-mgmt DB and the source code repository, and hands back the state both
the API (api/app.py) and the Celery worker (tasks/workflow.py) need.
`Components` keeps the workflow steps (cloning, generating, combined run) as
separate, stateless use-case factories.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from adapters.analysis.manual_source_analyzer import ManualSourceAnalyzer
from adapters.config import config_path, get_config
from adapters.json_model_setup_data_writer import JsonModelSetupDataWriter
from adapters.mysql_config_management_repository import MysqlConfigManagementRepository
from adapters.source_code.make_build_runner import MakeBuildRunner
from adapters.source_code.git_source_code_repository import GitSourceCodeRepository
from model.data_source import SourceType
from model.validation import MandatoryFieldRule
from ports.config_management_repository import IConfigManagementRepository
from ports.source_code_repository import ISourceCodeRepository
from use_cases.acquire_project_context import AcquireProjectContextUseCase
from use_cases.analyze_software_units import AnalyzeSoftwareUnitsUseCase
from use_cases.build_software_unit_inventory import BuildSoftwareUnitInventoryUseCase
from use_cases.clone_software_units import CloneSoftwareUnitsUseCase
from use_cases.generate_model_setup_data import GenerateModelSetupDataUseCase
from use_cases.run_workflow import RunWorkflowUseCase
from use_cases.validate_mandatory_fields import ValidateMandatoryFieldsUseCase

MSD_ROOT = Path(__file__).resolve().parents[1]
ENV_WORKSPACE = "MSD_WORKSPACE"

_VALIDATION_RULES = [
    MandatoryFieldRule("file_name", "AcquiredFile"),
    MandatoryFieldRule("name", "ExtractedTopic"),
]


@dataclass
class Components:
    config_repo: IConfigManagementRepository
    source_repo: ISourceCodeRepository
    workspace: Path

    def clone_uc(self) -> CloneSoftwareUnitsUseCase:
        return CloneSoftwareUnitsUseCase(
            project_context_uc=AcquireProjectContextUseCase(self.config_repo),
            inventory_uc=BuildSoftwareUnitInventoryUseCase(self.config_repo),
            source_repo=self.source_repo,
        )

    def generate_uc(self, selection_dir: Path) -> GenerateModelSetupDataUseCase:
        config = get_config()
        return GenerateModelSetupDataUseCase(
            project_context_uc=AcquireProjectContextUseCase(self.config_repo),
            inventory_uc=BuildSoftwareUnitInventoryUseCase(self.config_repo),
            source_repo=self.source_repo,
            analyze_uc=AnalyzeSoftwareUnitsUseCase(
                ManualSourceAnalyzer(config.analyzer),
                MakeBuildRunner(config.analyzer.makefile_include_patterns),
                run_build=config.analyzer.run_build,
            ),
            validate_uc=ValidateMandatoryFieldsUseCase(list(_VALIDATION_RULES)),
            writer=JsonModelSetupDataWriter(selection_dir),
            config_repo=self.config_repo,
        )

    def workflow_uc(self) -> RunWorkflowUseCase:
        return RunWorkflowUseCase(clone_uc=self.clone_uc(), generate_uc_factory=self.generate_uc)


def load_components(
    workspace: Optional[Path] = None,
) -> Components:
    config_file = config_path()
    config = get_config()

    config_mgmt = next((c for c in config.data_sources if c.source_type == SourceType.CONFIG_MGMT_DB), None)
    source_repo_cfg = next((c for c in config.data_sources if c.source_type == SourceType.SOURCE_CODE_REPO), None)
    if config_mgmt is None:
        raise RuntimeError(f"no config_mgmt_db data source configured in {config_file}")
    if source_repo_cfg is None:
        raise RuntimeError(f"no source_code_repo data source configured in {config_file}")

    root = workspace or Path(os.environ.get(ENV_WORKSPACE) or (MSD_ROOT / "workspace"))
    return Components(
        config_repo=MysqlConfigManagementRepository.from_data_source_config(config_mgmt),
        source_repo=GitSourceCodeRepository.from_data_source_config(
            source_repo_cfg, config.analyzer.makefile_include_patterns
        ),
        workspace=root,
    )
