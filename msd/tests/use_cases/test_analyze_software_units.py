from pathlib import Path
from typing import List

import pytest

from model.inventory import SoftwareUnitVersion, SoftwareUnitVersionInventory
from model.project_context import ProjectContext, PlatformRecord, ProjectRecord, VersionRecord
from model.extracted_topic import ExtractedTopic, TopicRole
from ports.build_runner import IBuildRunner
from ports.source_analyzer import ISourceAnalyzer
from use_cases.analyze_software_units import AnalyzeSoftwareUnitsUseCase


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


def _inventory() -> SoftwareUnitVersionInventory:
    context = ProjectContext(
        project=ProjectRecord("proj-1", "skywatch"),
        platform=PlatformRecord("plat-1", "proj-1", "nftw"),
        version=VersionRecord("1.0.0", "proj-1", "plat-1", "1.0.0", is_effective=True),
    )
    return SoftwareUnitVersionInventory(context=context, units=[SoftwareUnitVersion("nav_app", "1.0.0")])


def test_run_build_false_never_touches_build_runner(tmp_path):
    build_runner = _FakeBuildRunner()
    analyzer = _FakeAnalyzer()

    AnalyzeSoftwareUnitsUseCase(analyzer, build_runner, run_build=False).execute(_inventory(), tmp_path)

    assert build_runner.ensure_calls == []
    assert build_runner.regenerate_calls == []
    assert analyzer.calls == ["nav_app"]


def test_run_build_true_raises_when_gmake_unavailable(tmp_path):
    build_runner = _FakeBuildRunner(gmake_available=False)
    analyzer = _FakeAnalyzer()

    with pytest.raises(RuntimeError, match="gmake is not available"):
        AnalyzeSoftwareUnitsUseCase(analyzer, build_runner, run_build=True).execute(_inventory(), tmp_path)

    assert analyzer.calls == []


def test_run_build_true_regenerates_each_unit_before_analysis(tmp_path):
    build_runner = _FakeBuildRunner()
    analyzer = _FakeAnalyzer()

    AnalyzeSoftwareUnitsUseCase(analyzer, build_runner, run_build=True).execute(_inventory(), tmp_path)

    assert build_runner.ensure_calls == [1]
    assert build_runner.regenerate_calls == [tmp_path / "nav_app"]
    assert analyzer.calls == ["nav_app"]
