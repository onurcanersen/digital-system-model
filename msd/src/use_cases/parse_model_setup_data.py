"""Use case: parse previously cloned repositories into Model Setup Data (SRS DSM-MSD req 19).

The parse step is decoupled from the clone step: this use case never reaches
the source code repository over the network. It scans the unit directories
already present under `dest_root` (produced by CloneSourceRepositoriesUseCase
or an earlier run) and builds the Model Setup Data artifact from them. Units
that were not cloned are recorded as errors, not fetched on the fly.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from model.acquired_file import AcquiredFile, FileAccessError
from model.model_setup_data import ModelSetupData
from model.status import AcquisitionStatus
from ports.config_management_repository import IConfigManagementRepository
from ports.model_setup_data_writer import IModelSetupDataWriter
from ports.source_code_repository import ISourceCodeRepository
from use_cases.acquire_project_context import AcquireProjectContextUseCase
from use_cases.analyze_source_units import AnalyzeSourceUnitsUseCase
from use_cases.build_software_unit_inventory import BuildSoftwareUnitInventoryUseCase
from use_cases.fetch_source_files import missing_mandatory_file_records
from use_cases.validate_mandatory_fields import ValidateMandatoryFieldsUseCase

logger = logging.getLogger(__name__)


class ParseModelSetupDataUseCase:
    """Parses the cloned unit repositories for a selected project/platform/version
    and writes the Model Setup Data file (req 19), reusing previously cloned
    repositories found under `dest_root`."""

    def __init__(
        self,
        project_context_uc: AcquireProjectContextUseCase,
        inventory_uc: BuildSoftwareUnitInventoryUseCase,
        source_repo: ISourceCodeRepository,
        analyze_uc: AnalyzeSourceUnitsUseCase,
        validate_uc: ValidateMandatoryFieldsUseCase,
        writer: IModelSetupDataWriter,
        config_repo: IConfigManagementRepository,
    ):
        self._project_context_uc = project_context_uc
        self._inventory_uc = inventory_uc
        self._source_repo = source_repo
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
        acquired_files: List[AcquiredFile] = []
        for unit in inventory.units:
            clone_path = dest_root / unit.unit_name
            if not clone_path.is_dir():
                logger.warning("generate: %s %s is not cloned under %s, recording errors",
                               unit.unit_name, unit.version, dest_root)
                acquired_files.extend(self._not_cloned_records(unit))
                continue
            found = self._source_repo.scan_cloned_unit(unit, clone_path)
            found_names = {Path(f.file_path).name for f in found}
            acquired_files.extend(found)
            mandatory = self._source_repo.list_mandatory_files(unit.unit_name)
            missing = missing_mandatory_file_records(unit, mandatory, found_names, datetime.now())
            acquired_files.extend(missing)
            logger.info("generate: %s %s scanned %d file(s), %d missing mandatory",
                        unit.unit_name, unit.version, len(found), len(missing))

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
        logger.info("generate: wrote model setup data to %s", output_path)
        return data

    def _not_cloned_records(self, unit) -> List[AcquiredFile]:
        now = datetime.now()
        error = FileAccessError(
            file_path=unit.unit_name,
            error_type="access",
            message=f"repository '{unit.unit_name}' is not cloned under the workspace; run the clone step first",
        )
        return [
            AcquiredFile(
                unit_name=unit.unit_name,
                file_name=Path(relative_path).name,
                file_path=relative_path,
                package_version=unit.version,
                updated_at=now,
                status=AcquisitionStatus.ERROR,
                errors=[error],
            )
            for relative_path in self._source_repo.list_mandatory_files(unit.unit_name)
        ]
