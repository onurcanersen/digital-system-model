"""Tests for GenerateModelSetupData — the generate step must reuse previously
cloned repositories and never reach the source repository itself
(SRS DSM-MSD req 14-16, 19)."""

import json
from pathlib import Path
from typing import List

from msd.adapters.json_model_setup_data_writer import JsonModelSetupDataWriter
from fakes.fake_config_management_repository import FakeConfigManagementRepository
from fakes.fake_source_code_repository import FakeSourceCodeRepository
from msd.domain.inventory import CandidateUnitVersion, SoftwareUnitVersion
from msd.domain.status import AcquisitionStatus
from msd.domain.extracted_topic import ExtractedTopic, TopicRole
from msd.domain.validation import MandatoryFieldRule
from msd.ports.source_analyzer import ISourceAnalyzer
from msd.services.acquire_project_context import AcquireProjectContext
from msd.services.analyze_software_units import AnalyzeSoftwareUnits
from msd.services.build_software_unit_inventory import BuildSoftwareUnitInventory
from msd.services.generate_model_setup_data import GenerateModelSetupData
from msd.services.validate_mandatory_fields import ValidateMandatoryFields


class _FakeAnalyzer(ISourceAnalyzer):
    def extract(self, folder_path: Path, folder_name: str) -> List[ExtractedTopic]:
        return [ExtractedTopic(source_folder=folder_name, name="nav_position", role=TopicRole.PUB)]


class _FakeBuildRunner:
    def ensure_available(self) -> None:
        pass

    def regenerate_code(self, unit_dir: Path) -> None:
        pass


def _use_case(source_repo, root: Path, config_repo=None):
    config_repo = config_repo or FakeConfigManagementRepository(
        unit_versions={"1.0.0": [SoftwareUnitVersion("nav_app", "1.0.0")]}
    )
    return GenerateModelSetupData(
        project_context=AcquireProjectContext(config_repo),
        inventory=BuildSoftwareUnitInventory(config_repo),
        source_repo=source_repo,
        analyze=AnalyzeSoftwareUnits(_FakeAnalyzer(), _FakeBuildRunner()),
        validate=ValidateMandatoryFields([MandatoryFieldRule("file_name", "AcquiredFile")]),
        writer=JsonModelSetupDataWriter(root),
        config_repo=config_repo,
    )


def _write_cloned_unit(root: Path, unit_name: str, files: dict) -> None:
    unit_dir = root / unit_name
    for relative_path, content in files.items():
        path = unit_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def test_generates_from_previously_cloned_repos_and_writes_json(tmp_path: Path):
    root = tmp_path / "ws"
    _write_cloned_unit(root, "nav_app", {"Makefile": "all:\n", "src/nav_app.xml": "<manifest/>"})
    source_repo = FakeSourceCodeRepository(mandatory_files=["Makefile", "src/nav_app.xml"])

    data = _use_case(source_repo, root).execute(root, tmp_path / "out.json", "proj-1", "plat-1", "1.0.0")

    assert all(f.status == AcquisitionStatus.OK for f in data.acquired_files)
    assert data.validation_errors == []
    assert [u.unit_name for u in data.inventory.units] == ["nav_app"]
    assert (tmp_path / "out.json").exists()
    payload = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    # The file is the whole artifact, not just its graph: the acquisition and
    # validation records are what make the run traceable (req 14, 15, 18), and
    # this file is the only place they are kept.
    assert payload == data.to_dict()
    assert payload["graph"] == data.graph
    assert payload["context"]["project"]["project_id"] == "proj-1"
    assert [f["file_name"] for f in payload["acquired_files"]] == ["Makefile", "nav_app.xml"]
    assert payload["validation_errors"] == []
    assert payload["generated_at"] == data.generated_at.isoformat()


def test_records_the_producing_user_in_the_file(tmp_path: Path):
    """Provenance on the artifact (req 1): a listing reads the producer back
    out of the file, so it must survive the write."""
    root = tmp_path / "ws"
    _write_cloned_unit(root, "nav_app", {"Makefile": "all:\n", "src/nav_app.xml": "<manifest/>"})
    source_repo = FakeSourceCodeRepository(mandatory_files=["Makefile", "src/nav_app.xml"])

    data = _use_case(source_repo, root).execute(
        root, tmp_path / "out.json", "proj-1", "plat-1", "1.0.0", produced_by="operator"
    )

    assert data.produced_by == "operator"
    payload = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert payload["produced_by"] == "operator"


def test_records_no_producer_when_the_caller_names_none(tmp_path: Path):
    """msd authenticates nobody — a caller with no user context still produces
    a valid file."""
    root = tmp_path / "ws"
    _write_cloned_unit(root, "nav_app", {"Makefile": "all:\n", "src/nav_app.xml": "<manifest/>"})
    source_repo = FakeSourceCodeRepository(mandatory_files=["Makefile", "src/nav_app.xml"])

    _use_case(source_repo, root).execute(root, tmp_path / "out.json", "proj-1", "plat-1", "1.0.0")

    payload = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert payload["produced_by"] is None


def test_records_the_candidate_version_in_the_written_inventory(tmp_path: Path):
    """Req 11: the produced file's Software Unit Version Inventory must name
    the candidate version under evaluation, flagged as such, and the graph
    built from that inventory must agree with it."""
    root = tmp_path / "ws"
    _write_cloned_unit(root, "nav_app", {"Makefile": "all:\n", "src/nav_app.xml": "<manifest/>"})
    source_repo = FakeSourceCodeRepository(mandatory_files=["Makefile", "src/nav_app.xml"])

    data = _use_case(source_repo, root).execute(
        root, tmp_path / "out.json", "proj-1", "plat-1", "1.0.0",
        candidate=CandidateUnitVersion("nav_app", "1.1.0-rc1"),
    )

    payload = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert payload["inventory"]["units"] == [
        {"unit_name": "nav_app", "version": "1.1.0-rc1", "is_candidate": True}
    ]
    # The acquired-file records carry the version they were acquired at (req 14).
    assert {f["package_version"] for f in payload["acquired_files"]} == {"1.1.0-rc1"}
    versions_by_app = {a["name"]: a["version"] for a in payload["graph"]["applications"]}
    assert versions_by_app["nav_app"] == "1.1.0-rc1"
    assert data.inventory.units[0].is_candidate is True


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
