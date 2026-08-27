from pathlib import Path
from typing import List

import pytest

from model.inventory import SoftwareUnitVersion, SoftwareUnitVersionInventory
from model.project_context import AcquisitionContext, PlatformRecord, ProjectRecord, VersionRecord
from model.topic_entry import TopicEntry
from ports.source_analyzer import ISourceAnalyzer
from use_cases.analyze_source_units import AnalyzeSourceUnitsUseCase


class _FakeAnalyzer(ISourceAnalyzer):
    def __init__(self):
        self.calls: List[str] = []

    def extract(self, folder_path: Path, folder_name: str) -> List[TopicEntry]:
        self.calls.append(folder_name)
        return [TopicEntry(source_folder=folder_name, name="topic", role="pub")]


def _inventory() -> SoftwareUnitVersionInventory:
    context = AcquisitionContext(
        project=ProjectRecord("proj-1", "skywatch"),
        platform=PlatformRecord("plat-1", "proj-1", "nftw"),
        version=VersionRecord("1.0.0", "proj-1", "plat-1", "1.0.0", is_effective=True),
    )
    return SoftwareUnitVersionInventory(context=context, units=[SoftwareUnitVersion("nav_app", "1.0.0")])


def test_run_build_false_never_touches_build_runner(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "use_cases.analyze_source_units.check_gmake_available",
        lambda: calls.append("check_gmake_available") or True,
    )
    analyzer = _FakeAnalyzer()

    AnalyzeSourceUnitsUseCase(analyzer, run_build=False).execute(_inventory(), tmp_path)

    assert calls == []
    assert analyzer.calls == ["nav_app"]


def test_run_build_true_raises_when_gmake_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr("use_cases.analyze_source_units.check_gmake_available", lambda: False)
    analyzer = _FakeAnalyzer()

    with pytest.raises(RuntimeError, match="gmake is not available"):
        AnalyzeSourceUnitsUseCase(analyzer, run_build=True).execute(_inventory(), tmp_path)

    assert analyzer.calls == []


def test_run_build_true_skips_build_when_no_valid_makefile_but_still_analyzes(tmp_path, monkeypatch):
    monkeypatch.setattr("use_cases.analyze_source_units.check_gmake_available", lambda: True)
    monkeypatch.setattr("use_cases.analyze_source_units.find_valid_makefile", lambda folder_path: None)
    build_calls = []
    monkeypatch.setattr(
        "use_cases.analyze_source_units.run_regenerate_code",
        lambda makefile_path: build_calls.append(makefile_path),
    )
    analyzer = _FakeAnalyzer()

    AnalyzeSourceUnitsUseCase(analyzer, run_build=True).execute(_inventory(), tmp_path)

    assert build_calls == []
    assert analyzer.calls == ["nav_app"]


def test_run_build_true_runs_regenerate_code_when_valid_makefile_found(tmp_path, monkeypatch):
    makefile_path = tmp_path / "nav_app" / "Makefile"
    monkeypatch.setattr("use_cases.analyze_source_units.check_gmake_available", lambda: True)
    monkeypatch.setattr("use_cases.analyze_source_units.find_valid_makefile", lambda folder_path: makefile_path)
    build_calls = []
    monkeypatch.setattr(
        "use_cases.analyze_source_units.run_regenerate_code",
        lambda path: (build_calls.append(path), (True, ""))[1],
    )
    analyzer = _FakeAnalyzer()

    AnalyzeSourceUnitsUseCase(analyzer, run_build=True).execute(_inventory(), tmp_path)

    assert build_calls == [makefile_path]
    assert analyzer.calls == ["nav_app"]
