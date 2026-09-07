"""Tests for BuildSoftwareUnitInventory — the Software Unit Version Inventory
and the candidate version under evaluation (SRS DSM-MSD req 10-11)."""

from fakes.fake_config_management_repository import FakeConfigManagementRepository
from msd.domain.inventory import CandidateUnitVersion, SoftwareUnitVersion
from msd.domain.project_context import ProjectContext, PlatformRecord, ProjectRecord, VersionRecord
from msd.services.build_software_unit_inventory import BuildSoftwareUnitInventory


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

    inventory = BuildSoftwareUnitInventory(repo).execute(context)

    assert [u.unit_name for u in inventory.units] == ["nav_app", "sensor_app"]
    assert inventory.context is context


def _repo_with_three_units() -> FakeConfigManagementRepository:
    return FakeConfigManagementRepository(
        unit_versions={
            "1.0.0": [
                SoftwareUnitVersion("nav_app", "1.0.0"),
                SoftwareUnitVersion("sensor_app", "1.0.0"),
                SoftwareUnitVersion("common_lib", "1.0.0"),
            ]
        }
    )


def test_candidate_replaces_that_units_version_and_leaves_the_others_alone():
    """Req 11: the candidate version of the unit under evaluation, together
    with the other software unit versions the system version defines."""
    inventory = BuildSoftwareUnitInventory(_repo_with_three_units()).execute(
        _context(), CandidateUnitVersion("sensor_app", "1.0.3")
    )

    by_unit = {u.unit_name: u for u in inventory.units}
    assert by_unit["sensor_app"].version == "1.0.3"
    assert by_unit["sensor_app"].is_candidate is True
    assert by_unit["nav_app"].version == "1.0.0"
    assert by_unit["nav_app"].is_candidate is False
    assert by_unit["common_lib"].version == "1.0.0"


def test_candidate_keeps_the_units_place_in_the_inventory():
    """The inventory is a record of the system environment, so evaluating one
    unit must not reshuffle it."""
    inventory = BuildSoftwareUnitInventory(_repo_with_three_units()).execute(
        _context(), CandidateUnitVersion("sensor_app", "1.0.3")
    )

    assert [u.unit_name for u in inventory.units] == ["nav_app", "sensor_app", "common_lib"]


def test_candidate_for_a_unit_the_system_version_does_not_define_is_added():
    """A candidate may be a unit being introduced, not only one being
    upgraded — it joins the inventory rather than being dropped."""
    inventory = BuildSoftwareUnitInventory(_repo_with_three_units()).execute(
        _context(), CandidateUnitVersion("weather_app", "0.1.0")
    )

    by_unit = {u.unit_name: u for u in inventory.units}
    assert len(inventory.units) == 4
    assert by_unit["weather_app"].version == "0.1.0"
    assert by_unit["weather_app"].is_candidate is True


def test_without_a_candidate_the_inventory_is_what_the_system_version_defines():
    inventory = BuildSoftwareUnitInventory(_repo_with_three_units()).execute(_context())

    assert [u.version for u in inventory.units] == ["1.0.0", "1.0.0", "1.0.0"]
    assert not any(u.is_candidate for u in inventory.units)
