import json
from datetime import datetime
from pathlib import Path
from typing import List

from adapters.json_model_setup_data_writer import JsonModelSetupDataWriter
from fakes.fake_config_management_repository import FakeConfigManagementRepository
from fakes.fake_source_code_repository import FakeSourceCodeRepository
from model.acquired_file import AcquiredFile
from model.inventory import SoftwareUnitVersion
from model.topic_entry import TopicEntry
from model.validation import MandatoryFieldRule
from ports.source_analyzer import ISourceAnalyzer
from use_cases.acquire_project_context import AcquireProjectContextUseCase
from use_cases.analyze_source_units import AnalyzeSourceUnitsUseCase
from use_cases.build_software_unit_inventory import BuildSoftwareUnitInventoryUseCase
from use_cases.fetch_source_files import FetchSourceFilesUseCase
from use_cases.generate_model_setup_data import GenerateModelSetupDataUseCase
from use_cases.validate_mandatory_fields import ValidateMandatoryFieldsUseCase


class _FakeAnalyzer(ISourceAnalyzer):
    def extract(self, folder_path: Path, folder_name: str) -> List[TopicEntry]:
        return [TopicEntry(source_folder=folder_name, name="nav_position", role="pub")]


def test_execute_composes_use_cases_and_round_trips_json(tmp_path):
    config_repo = FakeConfigManagementRepository(
        unit_versions={"1.0.0": [SoftwareUnitVersion("nav_app", "1.0.0")]}
    )
    source_repo = FakeSourceCodeRepository(
        mandatory_files=["Makefile"],
        clone_results={"nav_app": [AcquiredFile("nav_app", "Makefile", "Makefile", "1.0.0", datetime.now())]},
    )
    writer = JsonModelSetupDataWriter(platform_name="nftw", project_name="skywatch", version="1.0.0", selection_dir=tmp_path / "workspace")

    use_case = GenerateModelSetupDataUseCase(
        project_context_uc=AcquireProjectContextUseCase(config_repo),
        inventory_uc=BuildSoftwareUnitInventoryUseCase(config_repo),
        fetch_files_uc=FetchSourceFilesUseCase(source_repo),
        analyze_uc=AnalyzeSourceUnitsUseCase(_FakeAnalyzer()),
        validate_uc=ValidateMandatoryFieldsUseCase([MandatoryFieldRule("file_name", "AcquiredFile")]),
        writer=writer,
        config_repo=config_repo,
    )

    output_path = tmp_path / "model_setup_data.json"
    data = use_case.execute(
        dest_root=tmp_path / "workspace",
        output_path=output_path,
        project_id="proj-1",
        platform_id="plat-1",
        version_id="1.0.0",
    )

    assert data.context.project.name == "skywatch"
    assert [u.unit_name for u in data.inventory.units] == ["nav_app"]
    assert data.validation_errors == []
    assert data.graph["metadata"]["scale"]["apps"] >= 0

    assert output_path.exists()
    round_tripped = json.loads(output_path.read_text(encoding="utf-8"))
    assert round_tripped == data.graph
    assert "context" not in round_tripped and "acquired_files" not in round_tripped


def test_execute_raises_when_context_cannot_be_acquired(tmp_path):
    config_repo = FakeConfigManagementRepository(platforms=[])
    source_repo = FakeSourceCodeRepository()
    writer = JsonModelSetupDataWriter(platform_name="nftw", project_name="skywatch", version="1.0.0", selection_dir=tmp_path / "workspace")

    use_case = GenerateModelSetupDataUseCase(
        project_context_uc=AcquireProjectContextUseCase(config_repo),
        inventory_uc=BuildSoftwareUnitInventoryUseCase(config_repo),
        fetch_files_uc=FetchSourceFilesUseCase(source_repo),
        analyze_uc=AnalyzeSourceUnitsUseCase(_FakeAnalyzer()),
        validate_uc=ValidateMandatoryFieldsUseCase([]),
        writer=writer,
        config_repo=config_repo,
    )

    try:
        use_case.execute(
            dest_root=tmp_path / "workspace",
            output_path=tmp_path / "out.json",
            project_id="proj-1",
            platform_id="plat-1",
            version_id="1.0.0",
        )
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "Cannot acquire project context" in str(exc)
