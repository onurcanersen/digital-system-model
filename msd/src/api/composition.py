"""Composition of the msd API's components from the saved data-source configs
(SRS DSM-MSD req 4), wiring the use cases that implement the selection,
cloning, and parsing workflow (req 5, 13, 19).

`load_components()` reads msd.ini (req 4), builds the real adapters
for the config-mgmt DB and the source code repository, and hands back the
state the API needs. `Components` keeps the three workflow steps (selection,
cloning, parsing) as separate, stateless use-case factories.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from adapters.analysis.manual_source_analyzer import ManualSourceAnalyzer
from adapters.config import config_path, get_config
from adapters.json_model_setup_data_writer import JsonModelSetupDataWriter
from adapters.mysql_config_management_repository import MysqlConfigManagementRepository
from adapters.source_code.git_source_code_repository import GitSourceCodeRepository
from model.data_source import SourceType
from model.validation import MandatoryFieldRule
from ports.config_management_repository import IConfigManagementRepository
from ports.source_code_repository import ISourceCodeRepository
from use_cases.acquire_project_context import AcquireProjectContextUseCase
from use_cases.analyze_source_units import AnalyzeSourceUnitsUseCase
from use_cases.build_software_unit_inventory import BuildSoftwareUnitInventoryUseCase
from use_cases.clone_source_repositories import CloneSourceRepositoriesUseCase
from use_cases.parse_model_setup_data import ParseModelSetupDataUseCase
from use_cases.validate_mandatory_fields import ValidateMandatoryFieldsUseCase

MSD_ROOT = Path(__file__).resolve().parents[2]
ENV_WORKSPACE = "MSD_WORKSPACE"

_VALIDATION_RULES = [
    MandatoryFieldRule("file_name", "AcquiredFile"),
    MandatoryFieldRule("name", "TopicEntry"),
]


def _sanitize(path_component: str) -> str:
    """Make a DB-provided id safe to use as a directory name."""
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", path_component)
    return sanitized or "_"


@dataclass
class Components:
    config_repo: IConfigManagementRepository
    source_repo: ISourceCodeRepository
    workspace: Path

    def selection_dir(self, project_id: str, platform_id: str, version_id: str) -> Path:
        """Workspace directory for one selection: <workspace>/<project>/<platform>/<version>.
        Holds the cloned unit repos (step 2) and model_setup_data.json (step 3)."""
        return self.selection_dir_under(self.workspace, project_id, platform_id, version_id)

    def selection_dir_under(self, root: Path, project_id: str, platform_id: str, version_id: str) -> Path:
        """<root>/<project>/<platform>/<version> with sanitized id components.
        `root` defaults to the workspace via selection_dir(); a per-task root
        (e.g. <workspace>/<task_id>) isolates one workflow run's artifacts."""
        return (
            root
            / _sanitize(project_id)
            / _sanitize(platform_id)
            / _sanitize(version_id)
        )

    def clone_uc(self) -> CloneSourceRepositoriesUseCase:
        return CloneSourceRepositoriesUseCase(
            project_context_uc=AcquireProjectContextUseCase(self.config_repo),
            inventory_uc=BuildSoftwareUnitInventoryUseCase(self.config_repo),
            source_repo=self.source_repo,
        )

    def parse_uc(self, platform_name: str, project_name: str, version: str, selection_dir: Path) -> ParseModelSetupDataUseCase:
        return ParseModelSetupDataUseCase(
            project_context_uc=AcquireProjectContextUseCase(self.config_repo),
            inventory_uc=BuildSoftwareUnitInventoryUseCase(self.config_repo),
            source_repo=self.source_repo,
            analyze_uc=AnalyzeSourceUnitsUseCase(
                ManualSourceAnalyzer(),
                run_build=get_config().analyzer.run_build,
            ),
            validate_uc=ValidateMandatoryFieldsUseCase(list(_VALIDATION_RULES)),
            writer=JsonModelSetupDataWriter(platform_name, project_name, version, selection_dir),
            config_repo=self.config_repo,
        )


def load_components(
    workspace: Optional[Path] = None,
) -> Components:
    config_file = config_path()
    configs = get_config().data_sources

    config_mgmt = next((c for c in configs if c.source_type == SourceType.CONFIG_MGMT_DB), None)
    source_repo_cfg = next((c for c in configs if c.source_type == SourceType.SOURCE_CODE_REPO), None)
    if config_mgmt is None:
        raise RuntimeError(f"no config_mgmt_db data source configured in {config_file}")
    if source_repo_cfg is None:
        raise RuntimeError(f"no source_code_repo data source configured in {config_file}")

    root = workspace or Path(os.environ.get(ENV_WORKSPACE) or (MSD_ROOT / "workspace"))
    return Components(
        config_repo=MysqlConfigManagementRepository.from_data_source_config(config_mgmt),
        source_repo=GitSourceCodeRepository.from_data_source_config(source_repo_cfg),
        workspace=root,
    )
