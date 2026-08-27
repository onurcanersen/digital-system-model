"""Use case: orchestrate Model Setup Data generation end-to-end (SRS DSM-MSD req 1, 5, 19)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from model.model_setup_data import ModelSetupData
from ports.config_management_repository import IConfigManagementRepository
from ports.model_setup_data_writer import IModelSetupDataWriter
from use_cases.acquire_project_context import AcquireProjectContextUseCase
from use_cases.analyze_source_units import AnalyzeSourceUnitsUseCase
from use_cases.build_software_unit_inventory import BuildSoftwareUnitInventoryUseCase
from use_cases.fetch_source_files import FetchSourceFilesUseCase
from use_cases.validate_mandatory_fields import ValidateMandatoryFieldsUseCase


class GenerateModelSetupDataUseCase:
    """Ensures the data underlying model construction is produced in a
    controlled, traceable, verifiable manner (req 1), tied to a selected
    project/platform/version (req 5), and prepares/saves it as the Model
    Setup Data file (req 19)."""

    def __init__(
        self,
        project_context_uc: AcquireProjectContextUseCase,
        inventory_uc: BuildSoftwareUnitInventoryUseCase,
        fetch_files_uc: FetchSourceFilesUseCase,
        analyze_uc: AnalyzeSourceUnitsUseCase,
        validate_uc: ValidateMandatoryFieldsUseCase,
        writer: IModelSetupDataWriter,
        config_repo: IConfigManagementRepository,
    ):
        self._project_context_uc = project_context_uc
        self._inventory_uc = inventory_uc
        self._fetch_files_uc = fetch_files_uc
        self._analyze_uc = analyze_uc
        self._validate_uc = validate_uc
        self._writer = writer
        self._config_repo = config_repo

    def execute(
        self,
        dest_root: Path,
        output_path: Path,
        project_id: Optional[str] = None,
        platform_id: Optional[str] = None,
        version_id: Optional[str] = None,
    ) -> ModelSetupData:
        context_result = self._project_context_uc.execute(project_id, platform_id, version_id)
        if context_result.context is None:
            raise RuntimeError(f"Cannot acquire project context: {context_result.error}")
        context = context_result.context

        inventory = self._inventory_uc.execute(context)

        dest_root.mkdir(parents=True, exist_ok=True)
        acquired_files = self._fetch_files_uc.execute(inventory, dest_root)
        topic_entries = self._analyze_uc.execute(inventory, dest_root)

        validation_errors = self._validate_uc.execute([*acquired_files, *topic_entries], context)

        graph = self._writer.build_graph(inventory, topic_entries, self._config_repo)

        data = ModelSetupData(
            context=context,
            inventory=inventory,
            acquired_files=acquired_files,
            graph=graph,
            validation_errors=validation_errors,
        )
        self._writer.write(data, output_path)
        return data
