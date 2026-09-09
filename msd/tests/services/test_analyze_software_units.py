import threading
import time
from pathlib import Path
from typing import List

import pytest

from msd.domain.inventory import SoftwareUnitVersion, SoftwareUnitVersionInventory
from msd.domain.project_context import ProjectContext, PlatformRecord, ProjectRecord, VersionRecord
from msd.domain.extracted_topic import ExtractedTopic, TopicRole
from msd.ports.build_runner import IBuildRunner
from msd.ports.source_analyzer import ISourceAnalyzer
from msd.services.analyze_software_units import AnalyzeSoftwareUnits
from msd.services.concurrency import UNIT_CONCURRENCY


class _FakeAnalyzer(ISourceAnalyzer):
    def __init__(self):
        self.calls: List[str] = []

    def extract(self, folder_path: Path, folder_name: str) -> List[ExtractedTopic]:
        self.calls.append(folder_name)
        return [ExtractedTopic(source_folder=folder_name, name="topic", role=TopicRole.PUB)]


class _FakeBuildRunner(IBuildRunner):
    def __init__(self, gmake_available: bool = True, makefile_path: Path = None):
        self._gmake_available = gmake_available
        self._makefile_path = makefile_path
        self.ensure_calls = []
        self.regenerate_calls: List[Path] = []

    def ensure_available(self) -> None:
        self.ensure_calls.append(1)
        if not self._gmake_available:
            raise RuntimeError("gmake is not available but build execution was requested")

    def regenerate_code(self, unit_dir: Path) -> None:
        self.regenerate_calls.append(unit_dir)


def _inventory(units=None) -> SoftwareUnitVersionInventory:
    context = ProjectContext(
        project=ProjectRecord("proj-1", "skywatch"),
        platform=PlatformRecord("plat-1", "proj-1", "nftw"),
        version=VersionRecord("1.0.0", "proj-1", "plat-1", "1.0.0", is_effective=True),
    )
    units = units or [SoftwareUnitVersion("nav_app", "1.0.0")]
    return SoftwareUnitVersionInventory(context=context, units=units)


def test_run_build_false_never_touches_build_runner(tmp_path):
    build_runner = _FakeBuildRunner()
    analyzer = _FakeAnalyzer()

    AnalyzeSoftwareUnits(analyzer, build_runner, run_build=False).execute(_inventory(), tmp_path)

    assert build_runner.ensure_calls == []
    assert build_runner.regenerate_calls == []
    assert analyzer.calls == ["nav_app"]


def test_run_build_true_raises_when_gmake_unavailable(tmp_path):
    build_runner = _FakeBuildRunner(gmake_available=False)
    analyzer = _FakeAnalyzer()

    with pytest.raises(RuntimeError, match="gmake is not available"):
        AnalyzeSoftwareUnits(analyzer, build_runner, run_build=True).execute(_inventory(), tmp_path)

    assert analyzer.calls == []


def test_run_build_true_regenerates_each_unit_before_analysis(tmp_path):
    build_runner = _FakeBuildRunner()
    analyzer = _FakeAnalyzer()

    AnalyzeSoftwareUnits(analyzer, build_runner, run_build=True).execute(_inventory(), tmp_path)

    assert build_runner.ensure_calls == [1]
    assert build_runner.regenerate_calls == [tmp_path / "nav_app"]
    assert analyzer.calls == ["nav_app"]


class _SleepingAnalyzer(ISourceAnalyzer):
    """An extraction that pauses, recording start/stop per unit so a test can
    tell how many units' analyses overlapped (and never exceeded the pool
    size)."""

    def __init__(self, delay_seconds: float = 0.1):
        self._delay = delay_seconds
        self.events: List[str] = []
        self._lock = threading.Lock()

    def extract(self, folder_path: Path, folder_name: str) -> List[ExtractedTopic]:
        with self._lock:
            self.events.append(f"{folder_name} start")
        time.sleep(self._delay)
        with self._lock:
            self.events.append(f"{folder_name} end")
        return [ExtractedTopic(source_folder=folder_name, name="topic", role=TopicRole.PUB)]


def test_analyzes_units_concurrently_and_keeps_inventory_order(tmp_path):
    """More units than the pool size: some extractions must overlap (that is
    what the concurrency buys) and never more than UNIT_CONCURRENCY run at
    once — while the extracted entries still come back in inventory order."""
    unit_names = ("nav_app", "sensor_app", "display_app", "comm_app", "power_app")
    build_runner = _FakeBuildRunner()
    analyzer = _SleepingAnalyzer()

    entries = AnalyzeSoftwareUnits(analyzer, build_runner).execute(
        _inventory([SoftwareUnitVersion(name, "1.0.0") for name in unit_names]), tmp_path
    )

    assert [entry.source_folder for entry in entries] == list(unit_names)
    in_flight = peak = 0
    for event in analyzer.events:
        in_flight += 1 if event.endswith("start") else -1
        peak = max(peak, in_flight)
    assert peak > 1, f"expected overlapping extractions, got sequential events: {analyzer.events}"
    assert peak <= UNIT_CONCURRENCY
