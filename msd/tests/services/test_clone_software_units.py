"""Tests for CloneSoftwareUnits — the standalone clone step (SRS DSM-MSD req 13, 16)."""

from pathlib import Path

from fakes.fake_config_management_repository import FakeConfigManagementRepository
from fakes.fake_source_code_repository import DiskCloningSourceCodeRepository
from msd.domain.inventory import SoftwareUnitVersion
from msd.domain.status import CloneStatus
from msd.services.acquire_project_context import AcquireProjectContext
from msd.services.build_software_unit_inventory import BuildSoftwareUnitInventory
from msd.services.clone_software_units import CloneSoftwareUnits


def _use_case(source_repo, config_repo=None):
    config_repo = config_repo or FakeConfigManagementRepository(
        unit_versions={"1.0.0": [SoftwareUnitVersion("nav_app", "1.0.0")]}
    )
    return CloneSoftwareUnits(
        project_context=AcquireProjectContext(config_repo),
        inventory=BuildSoftwareUnitInventory(config_repo),
        source_repo=source_repo,
    )


def test_clones_missing_units_and_skips_existing(tmp_path: Path):
    dest = tmp_path / "ws"
    use_case = _use_case(DiskCloningSourceCodeRepository())

    results = use_case.execute(dest, "proj-1", "plat-1", "1.0.0")
    assert [r.status for r in results] == [CloneStatus.CLONED]
    assert (dest / "nav_app" / "Makefile").is_file()
    assert (dest / "nav_app" / "src" / "nav_app.xml").is_file()

    results = use_case.execute(dest, "proj-1", "plat-1", "1.0.0")
    assert [r.status for r in results] == [CloneStatus.ALREADY_PRESENT]


def test_records_per_unit_error_without_aborting(tmp_path: Path):
    dest = tmp_path / "ws"
    config_repo = FakeConfigManagementRepository(
        unit_versions={
            "1.0.0": [
                SoftwareUnitVersion("nav_app", "1.0.0"),
                SoftwareUnitVersion("sensor_app", "1.0.0"),
            ]
        }
    )
    use_case = _use_case(DiskCloningSourceCodeRepository(fail_units={"nav_app"}), config_repo)

    results = use_case.execute(dest, "proj-1", "plat-1", "1.0.0")

    by_unit = {r.unit.unit_name: r for r in results}
    assert by_unit["nav_app"].status == CloneStatus.ERROR
    assert "cannot clone 'nav_app'" in by_unit["nav_app"].detail
    assert by_unit["sensor_app"].status == CloneStatus.CLONED
    assert (dest / "sensor_app" / "Makefile").is_file()


def test_raises_when_context_cannot_be_acquired(tmp_path: Path):
    config_repo = FakeConfigManagementRepository(platforms=[])
    use_case = _use_case(DiskCloningSourceCodeRepository(), config_repo)

    try:
        use_case.execute(tmp_path / "ws", "proj-1", "plat-1", "1.0.0")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "Cannot acquire project context" in str(exc)
