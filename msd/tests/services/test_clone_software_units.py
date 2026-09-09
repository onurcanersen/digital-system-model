"""Tests for CloneSoftwareUnits — the standalone clone step (SRS DSM-MSD req 13, 16)."""

import threading
import time
from pathlib import Path
from typing import List, Tuple

from fakes.fake_config_management_repository import FakeConfigManagementRepository
from fakes.fake_source_code_repository import DiskCloningSourceCodeRepository
from msd.domain.inventory import CandidateUnitVersion, SoftwareUnitVersion
from msd.domain.status import CloneStatus
from msd.services.acquire_project_context import AcquireProjectContext
from msd.services.build_software_unit_inventory import BuildSoftwareUnitInventory
from msd.services.clone_software_units import CloneSoftwareUnits
from msd.services.concurrency import UNIT_CONCURRENCY


def _use_case(source_repo, config_repo=None):
    config_repo = config_repo or FakeConfigManagementRepository(
        unit_versions={"1.0.0": [SoftwareUnitVersion("nav_app", "1.0.0")]}
    )
    return CloneSoftwareUnits(
        project_context=AcquireProjectContext(config_repo),
        inventory=BuildSoftwareUnitInventory(config_repo),
        source_repo=source_repo,
    )


def _max_in_flight(events: List[Tuple[str, str]]) -> int:
    """How many units' clones were in flight at once, from start/stop events."""
    in_flight = peak = 0
    for _, marker in events:
        in_flight += 1 if marker == "start" else -1
        peak = max(peak, in_flight)
    return peak


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


def test_clones_the_candidate_version_rather_than_the_one_the_system_version_pins(tmp_path: Path):
    """Req 11: the clone step must fetch the version under evaluation, since
    the version is the ref the source repository is asked for."""
    config_repo = FakeConfigManagementRepository(
        unit_versions={
            "1.0.0": [
                SoftwareUnitVersion("nav_app", "1.0.0"),
                SoftwareUnitVersion("sensor_app", "1.0.0"),
            ]
        }
    )
    source_repo = DiskCloningSourceCodeRepository()
    use_case = _use_case(source_repo, config_repo)

    results = use_case.execute(
        tmp_path / "ws", "proj-1", "plat-1", "1.0.0",
        candidate=CandidateUnitVersion("sensor_app", "1.0.3"),
    )

    assert sorted(source_repo.cloned) == [("nav_app", "1.0.0"), ("sensor_app", "1.0.3")]
    assert {r.unit.unit_name: r.unit.version for r in results} == {
        "nav_app": "1.0.0",
        "sensor_app": "1.0.3",
    }


def test_raises_when_context_cannot_be_acquired(tmp_path: Path):
    config_repo = FakeConfigManagementRepository(platforms=[])
    use_case = _use_case(DiskCloningSourceCodeRepository(), config_repo)

    try:
        use_case.execute(tmp_path / "ws", "proj-1", "plat-1", "1.0.0")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "Cannot acquire project context" in str(exc)


class _PausingCloningRepository(DiskCloningSourceCodeRepository):
    """A clone that pauses, recording start/stop per unit so a test can tell
    how many units' clones overlapped (and never exceeded the pool size)."""

    def __init__(self, delay_seconds: float = 0.1, **kwargs):
        super().__init__(**kwargs)
        self._delay = delay_seconds
        self.events: List[Tuple[str, str]] = []
        self._lock = threading.Lock()

    def clone_unit(self, unit, dest_dir):
        with self._lock:
            self.events.append((unit.unit_name, "start"))
        time.sleep(self._delay)
        with self._lock:
            self.events.append((unit.unit_name, "end"))
        super().clone_unit(unit, dest_dir)


def test_clones_units_concurrently_up_to_the_pool_limit(tmp_path: Path):
    """More units than the pool size: some clones must overlap (that is what
    the concurrency buys) and never more than UNIT_CONCURRENCY run at once —
    while the results still come back in inventory order."""
    unit_names = ("nav_app", "sensor_app", "display_app", "comm_app", "power_app")
    config_repo = FakeConfigManagementRepository(
        unit_versions={"1.0.0": [SoftwareUnitVersion(name, "1.0.0") for name in unit_names]}
    )
    source_repo = _PausingCloningRepository()
    use_case = _use_case(source_repo, config_repo)

    results = use_case.execute(tmp_path / "ws", "proj-1", "plat-1", "1.0.0")

    assert [r.unit.unit_name for r in results] == list(unit_names)
    assert all(r.status == CloneStatus.CLONED for r in results)
    assert _max_in_flight(source_repo.events) > 1, (
        f"expected overlapping clones, got sequential events: {source_repo.events}"
    )
    assert _max_in_flight(source_repo.events) <= UNIT_CONCURRENCY
