"""Tests for ParseModelSetupDataUseCase — the parse step must reuse previously
cloned repositories and never reach the source repository itself
(SRS DSM-MSD req 14-16, 19)."""

import json
from pathlib import Path
from typing import List

from adapters.json_model_setup_data_writer import JsonModelSetupDataWriter
from fakes.fake_config_management_repository import FakeConfigManagementRepository
from fakes.fake_source_code_repository import FakeSourceCodeRepository
from model.inventory import SoftwareUnitVersion
from model.status import AcquisitionStatus
from model.topic_entry import TopicEntry
from model.validation import MandatoryFieldRule
from ports.source_analyzer import ISourceAnalyzer
from use_cases.acquire_project_context import AcquireProjectContextUseCase
from use_cases.analyze_source_units import AnalyzeSourceUnitsUseCase
from use_cases.build_software_unit_inventory import BuildSoftwareUnitInventoryUseCase
from use_cases.parse_model_setup_data import ParseModelSetupDataUseCase
from use_cases.validate_mandatory_fields import ValidateMandatoryFieldsUseCase


class _FakeAnalyzer(ISourceAnalyzer):
    def extract(self, folder_path: Path, folder_name: str) -> List[TopicEntry]:
        return [TopicEntry(source_folder=folder_name, name="nav_position", role="pub")]


def _use_case(source_repo, root: Path, config_repo=None):
    config_repo = config_repo or FakeConfigManagementRepository(
        unit_versions={"1.0.0": [SoftwareUnitVersion("nav_app", "1.0.0")]}
    )
    return ParseModelSetupDataUseCase(
        project_context_uc=AcquireProjectContextUseCase(config_repo),
        inventory_uc=BuildSoftwareUnitInventoryUseCase(config_repo),
        source_repo=source_repo,
        analyze_uc=AnalyzeSourceUnitsUseCase(_FakeAnalyzer()),
        validate_uc=ValidateMandatoryFieldsUseCase([MandatoryFieldRule("file_name", "AcquiredFile")]),
        writer=JsonModelSetupDataWriter(platform_name="nftw", project_name="skywatch",
                                      version="1.0.0", selection_dir=root),
        config_repo=config_repo,
    )


def _write_cloned_unit(root: Path, unit_name: str, files: dict) -> None:
    unit_dir = root / unit_name
    for relative_path, content in files.items():
        path = unit_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def test_parses_previously_cloned_repos_and_writes_json(tmp_path: Path):
    root = tmp_path / "ws"
    _write_cloned_unit(root, "nav_app", {"Makefile": "all:\n", "src/nav_app.xml": "<manifest/>"})
    source_repo = FakeSourceCodeRepository(mandatory_files=["Makefile", "src/nav_app.xml"])

    data = _use_case(source_repo, root).execute(root, tmp_path / "out.json", "proj-1", "plat-1", "1.0.0")

    assert all(f.status == AcquisitionStatus.OK for f in data.acquired_files)
    assert data.validation_errors == []
    assert [u.unit_name for u in data.inventory.units] == ["nav_app"]
    assert (tmp_path / "out.json").exists()
    payload = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert payload == data.graph
    assert "context" not in payload and "acquired_files" not in payload


def test_reports_not_cloned_units_as_errors(tmp_path: Path):
    root = tmp_path / "ws"  # nothing cloned
    source_repo = FakeSourceCodeRepository(mandatory_files=["Makefile", "src/nav_app.xml"])

    data = _use_case(source_repo, root).execute(root, tmp_path / "out.json", "proj-1", "plat-1", "1.0.0")

    assert len(data.acquired_files) == 2
    assert all(f.status == AcquisitionStatus.ERROR for f in data.acquired_files)
    assert all(
        "not cloned" in error.message for f in data.acquired_files for error in f.errors
    )
    assert (tmp_path / "out.json").exists()


def test_missing_mandatory_file_gets_missing_data_status(tmp_path: Path):
    root = tmp_path / "ws"
    _write_cloned_unit(root, "nav_app", {"Makefile": "all:\n"})  # topic manifest absent
    source_repo = FakeSourceCodeRepository(mandatory_files=["Makefile", "src/nav_app.xml"])

    data = _use_case(source_repo, root).execute(root, tmp_path / "out.json", "proj-1", "plat-1", "1.0.0")

    by_name = {f.file_name: f for f in data.acquired_files}
    assert by_name["Makefile"].status == AcquisitionStatus.OK
    assert by_name["nav_app.xml"].status == AcquisitionStatus.MISSING_DATA


def test_raises_when_context_cannot_be_acquired(tmp_path: Path):
    config_repo = FakeConfigManagementRepository(platforms=[])
    source_repo = FakeSourceCodeRepository()

    try:
        _use_case(source_repo, tmp_path / "ws", config_repo).execute(
            tmp_path / "ws", tmp_path / "out.json", "proj-1", "plat-1", "1.0.0"
        )
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "Cannot acquire project context" in str(exc)
