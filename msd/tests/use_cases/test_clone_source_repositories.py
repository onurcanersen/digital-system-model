"""Tests for CloneSourceRepositoriesUseCase — the standalone clone step (SRS DSM-MSD req 13, 16)."""

from pathlib import Path

from fakes.fake_config_management_repository import FakeConfigManagementRepository
from fakes.fake_source_code_repository import FakeSourceCodeRepository
from model.inventory import SoftwareUnitVersion
from ports.source_code_repository import SourceRepoAccessError
from use_cases.acquire_project_context import AcquireProjectContextUseCase
from use_cases.build_software_unit_inventory import BuildSoftwareUnitInventoryUseCase
from use_cases.clone_source_repositories import (
    CLONE_STATUS_ALREADY_PRESENT,
    CLONE_STATUS_CLONED,
    CLONE_STATUS_ERROR,
    CloneSourceRepositoriesUseCase,
)


class _DiskCloningRepository(FakeSourceCodeRepository):
    """Clone that actually writes the unit directory to disk, like the git adapter."""

    def __init__(self, fail_units=()):
        super().__init__()
        self._fail_units = set(fail_units)

    def clone_unit(self, unit, dest_dir):
        if unit.unit_name in self._fail_units:
            raise SourceRepoAccessError(f"cannot clone '{unit.unit_name}'")
        unit_dir = dest_dir / unit.unit_name
        (unit_dir / "src").mkdir(parents=True, exist_ok=True)
        (unit_dir / "Makefile").write_text("all:\n", encoding="utf-8")
        (unit_dir / "src" / f"{unit.unit_name}.xml").write_text("<manifest/>", encoding="utf-8")
        return super().clone_unit(unit, dest_dir)


def _use_case(source_repo, config_repo=None):
    config_repo = config_repo or FakeConfigManagementRepository(
        unit_versions={"1.0.0": [SoftwareUnitVersion("nav_app", "1.0.0")]}
    )
    return CloneSourceRepositoriesUseCase(
        project_context_uc=AcquireProjectContextUseCase(config_repo),
        inventory_uc=BuildSoftwareUnitInventoryUseCase(config_repo),
        source_repo=source_repo,
    )


def test_clones_missing_units_and_skips_existing(tmp_path: Path):
    dest = tmp_path / "ws"
    use_case = _use_case(_DiskCloningRepository())

    results = use_case.execute(dest, "proj-1", "plat-1", "1.0.0")
    assert [r.status for r in results] == [CLONE_STATUS_CLONED]
    assert (dest / "nav_app" / "Makefile").is_file()
    assert (dest / "nav_app" / "src" / "nav_app.xml").is_file()

    results = use_case.execute(dest, "proj-1", "plat-1", "1.0.0")
    assert [r.status for r in results] == [CLONE_STATUS_ALREADY_PRESENT]


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
    use_case = _use_case(_DiskCloningRepository(fail_units={"nav_app"}), config_repo)

    results = use_case.execute(dest, "proj-1", "plat-1", "1.0.0")

    by_unit = {r.unit.unit_name: r for r in results}
    assert by_unit["nav_app"].status == CLONE_STATUS_ERROR
    assert "cannot clone 'nav_app'" in by_unit["nav_app"].detail
    assert by_unit["sensor_app"].status == CLONE_STATUS_CLONED
    assert (dest / "sensor_app" / "Makefile").is_file()


def test_raises_when_context_cannot_be_acquired(tmp_path: Path):
    config_repo = FakeConfigManagementRepository(platforms=[])
    use_case = _use_case(_DiskCloningRepository(), config_repo)

    try:
        use_case.execute(tmp_path / "ws", "proj-1", "plat-1", "1.0.0")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "Cannot acquire project context" in str(exc)
