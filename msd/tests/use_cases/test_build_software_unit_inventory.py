from fakes.fake_config_management_repository import FakeConfigManagementRepository
from model.inventory import SoftwareUnitVersion
from model.project_context import ProjectContext, PlatformRecord, ProjectRecord, VersionRecord
from use_cases.build_software_unit_inventory import BuildSoftwareUnitInventoryUseCase


def _context() -> ProjectContext:
    return ProjectContext(
        project=ProjectRecord("proj-1", "skywatch"),
        platform=PlatformRecord("plat-1", "proj-1", "nftw"),
        version=VersionRecord("1.0.0", "proj-1", "plat-1", "1.0.0", is_effective=True),
    )


def test_execute_builds_inventory_from_config_repository():
    context = _context()
    repo = FakeConfigManagementRepository(
        unit_versions={"1.0.0": [SoftwareUnitVersion("nav_app", "1.0.0"), SoftwareUnitVersion("sensor_app", "1.0.0")]}
    )

    inventory = BuildSoftwareUnitInventoryUseCase(repo).execute(context)

    assert [u.unit_name for u in inventory.units] == ["nav_app", "sensor_app"]
    assert inventory.context is context


def test_apply_candidate_replaces_unit_version_with_candidate():
    context = _context()
    repo = FakeConfigManagementRepository(unit_versions={"1.0.0": [SoftwareUnitVersion("nav_app", "1.0.0")]})
    use_case = BuildSoftwareUnitInventoryUseCase(repo)
    inventory = use_case.execute(context)

    updated = use_case.apply_candidate(inventory, "nav_app", "1.1.0-rc1")

    candidate = next(u for u in updated.units if u.unit_name == "nav_app")
    assert candidate.version == "1.1.0-rc1"
    assert candidate.is_candidate is True
    assert len(updated.units) == 1
