"""Use case: generate Model Setup Data from previously cloned repositories (SRS DSM-MSD req 19).

The generate step is decoupled from the clone step: this use case never reaches
the source code repository over the network. It scans the unit directories
already present under `dest_root` (produced by CloneSoftwareUnits
or an earlier run) and builds the Model Setup Data artifact from them. Units
that were not cloned are recorded as errors, not fetched on the fly.

The per-unit scans run up to UNIT_CONCURRENCY units at once (see
services/concurrency.py); the acquired-file records come back in inventory
order.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from msd.domain.acquired_file import AcquiredFile, FileAccessError
from msd.domain.inventory import CandidateUnitVersion, SoftwareUnitVersion
from msd.domain.model_setup_data import ModelSetupData
from msd.domain.status import AcquisitionStatus
from msd.ports.config_management_repository import IConfigManagementRepository
from msd.ports.model_setup_data_writer import IModelSetupDataWriter
from msd.ports.source_code_repository import ISourceCodeRepository
from msd.services.acquire_project_context import AcquireProjectContext
from msd.services.analyze_software_units import AnalyzeSoftwareUnits
from msd.services.build_software_unit_inventory import BuildSoftwareUnitInventory
from msd.services.concurrency import run_units_concurrently
from msd.services.progress import PHASE_FINALIZE, PHASE_SCAN
from msd.services.validate_mandatory_fields import ValidateMandatoryFields

logger = logging.getLogger(__name__)


def missing_mandatory_file_records(
    unit: SoftwareUnitVersion,
    mandatory: List[str],
    found_names: set,
    now: datetime,
) -> List[AcquiredFile]:
    """MISSING_DATA records for mandatory files absent from `found_names` (req 15),
    for a unit whose repository was already cloned."""
    return [
        AcquiredFile(
            unit_name=unit.unit_name,
            file_name=Path(relative_path).name,
            file_path=relative_path,
            package_version=unit.version,
            updated_at=now,
            status=AcquisitionStatus.MISSING_DATA,
        )
        for relative_path in mandatory
        if Path(relative_path).name not in found_names
    ]


class GenerateModelSetupData:
    """Generates the Model Setup Data from the cloned unit repositories for a selected
    project/platform/version (req 19), reusing previously cloned
    repositories found under `dest_root`."""

    def __init__(
        self,
        project_context: AcquireProjectContext,
        inventory: BuildSoftwareUnitInventory,
        source_repo: ISourceCodeRepository,
        analyze: AnalyzeSoftwareUnits,
        validate: ValidateMandatoryFields,
        writer: IModelSetupDataWriter,
        config_repo: IConfigManagementRepository,
    ):
        self._project_context = project_context
        self._inventory = inventory
        self._source_repo = source_repo
        self._analyze = analyze
        self._validate = validate
        self._writer = writer
        self._config_repo = config_repo

    def execute(
        self,
        dest_root: Path,
        output_path: Path,
        project_id: Optional[str] = None,
        platform_id: Optional[str] = None,
        version_id: Optional[str] = None,
        produced_by: Optional[str] = None,
        candidate: Optional[CandidateUnitVersion] = None,
        progress: Optional[Callable[[str, int, int], None]] = None,
    ) -> ModelSetupData:
        context_result = self._project_context.execute(project_id, platform_id, version_id)
        if context_result.context is None:
            raise RuntimeError(f"Cannot acquire project context: {context_result.error}")
        context = context_result.context

        # The same candidate the clone step was given, so the inventory this
        # run records — and the graph built from it — describes the versions
        # that were actually acquired (req 11).
        inventory = self._inventory.execute(context, candidate)

        units = inventory.units
        # The pool helper reports (0, N) up front; the acquired-file records
        # are flattened back into inventory order below, so the artifact lists
        # a unit's files together regardless of which unit finished first.
        dest_root.mkdir(parents=True, exist_ok=True)
        records_per_unit = run_units_concurrently(
            units, lambda unit: self._scan_one(unit, dest_root), PHASE_SCAN, progress
        )
        acquired_files: List[AcquiredFile] = [
            record for unit_records in records_per_unit for record in unit_records
        ]

        # The analyze step works the same inventory and carries on the same
        # progress: its phase follows the scan's.
        extracted_topics = self._analyze.execute(inventory, dest_root, progress=progress)

        # Everything after the per-unit work is one unit of progress: validate,
        # build the graph, write the file.
        if progress is not None:
            progress(PHASE_FINALIZE, 0, 1)
        validation_errors = self._validate.execute([*acquired_files, *extracted_topics], context)

        graph = self._writer.build_graph(context, inventory, extracted_topics, self._config_repo)

        data = ModelSetupData(
            context=context,
            inventory=inventory,
            acquired_files=acquired_files,
            graph=graph,
            validation_errors=validation_errors,
            produced_by=produced_by,
        )
        self._writer.write(data, output_path)
        logger.info("generate: wrote model setup data to %s", output_path)
        if progress is not None:
            progress(PHASE_FINALIZE, 1, 1)
        return data

    def _scan_one(self, unit: SoftwareUnitVersion, dest_root: Path) -> List[AcquiredFile]:
        """The per-unit scan: the mandatory-file records (found plus missing)
        for a cloned unit, or not-cloned error records for one the clone step
        did not produce (req 14, 15)."""
        clone_path = dest_root / unit.unit_name
        if not clone_path.is_dir():
            logger.warning("generate: %s %s is not cloned under %s, recording errors",
                           unit.unit_name, unit.version, dest_root)
            return self._not_cloned_records(unit)
        found = self._source_repo.scan_cloned_unit(unit, clone_path)
        found_names = {Path(f.file_path).name for f in found}
        mandatory = self._source_repo.list_mandatory_files(unit.unit_name)
        missing = missing_mandatory_file_records(unit, mandatory, found_names, datetime.now())
        logger.info("generate: %s %s scanned %d file(s), %d missing mandatory",
                    unit.unit_name, unit.version, len(found), len(missing))
        return [*found, *missing]

    def _not_cloned_records(self, unit: SoftwareUnitVersion) -> List[AcquiredFile]:
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
