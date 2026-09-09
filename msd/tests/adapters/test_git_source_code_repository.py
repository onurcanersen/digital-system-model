"""Pure unit test for mandatory_file_catalog.py's Makefile content-pattern
check (used by both git_source_code_repository.py and gmake_build_runner.py),
plus the git adapter's version listing — the set a candidate version is chosen
from (SRS DSM-MSD req 11), whose git invocation is mocked at the subprocess
boundary (real cloning stays manually verified, not automated)."""

import subprocess
from pathlib import Path

import pytest

from msd.adapters.source_code.git_source_code_repository import (
    GitSourceCodeRepository,
    natural_version_key,
)
from msd.adapters.source_code.mandatory_file_catalog import makefile_has_valid_include
from msd.domain.inventory import SoftwareUnitVersion
from msd.domain.status import AcquisitionStatus
from msd.ports.source_code_repository import SourceRepoAccessError, SourceRepoAuthError


def test_returns_true_when_pattern_present():
    content = "include include/Makefile_java.mk\n\n.PHONY: build\n"
    assert makefile_has_valid_include(content, ["include/Makefile_java.mk"]) is True


def test_returns_false_when_pattern_absent():
    content = ".PHONY: build\nbuild:\n\techo building\n"
    assert makefile_has_valid_include(content, ["include/Makefile_java.mk"]) is False


def test_ignores_pattern_inside_a_comment():
    content = "# include include/Makefile_java.mk\n.PHONY: build\n"
    assert makefile_has_valid_include(content, ["include/Makefile_java.mk"]) is False


def test_empty_pattern_list_never_matches():
    content = "include include/Makefile_java.mk\n"
    assert makefile_has_valid_include(content, []) is False


def test_matches_any_of_multiple_configured_patterns():
    content = "include include/Makefile_cpp.mk\n"
    patterns = ["include/Makefile_java.mk", "include/Makefile_cpp.mk"]
    assert makefile_has_valid_include(content, patterns) is True


# --------------------------------------------------------------- versions

def _repository() -> GitSourceCodeRepository:
    return GitSourceCodeRepository(
        base_url="http://gitea:3000",
        org="dsm-src",
        user="dsm",
        password="dsm",
        makefile_include_patterns=["include/Makefile_java.mk"],
    )


def _fake_git(monkeypatch, stdout="", returncode=0, stderr="", captured=None):
    def fake_run(cmd, **kwargs):
        if captured is not None:
            captured.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(
        "msd.adapters.source_code.git_source_code_repository.subprocess.run", fake_run
    )


def test_version_ordering_is_numeric_not_lexicographic():
    """1.0.10 is a later version than 1.0.9, which a plain string sort gets
    backwards — a candidate picker that offered them in that order would be
    telling the user the wrong thing."""
    versions = ["1.0.9", "1.0.10", "1.0.2", "2.0.0"]

    assert sorted(versions, key=natural_version_key, reverse=True) == [
        "2.0.0", "1.0.10", "1.0.9", "1.0.2",
    ]


def test_version_ordering_handles_non_numeric_versions():
    """Release-candidate and text versions must sort without raising, however
    they are shaped."""
    versions = ["1.0.0", "1.1.0-rc1", "main", "1.0.0"]

    assert sorted(versions, key=natural_version_key)  # no TypeError


def test_lists_the_units_published_versions_newest_first(monkeypatch):
    captured = []
    _fake_git(
        monkeypatch,
        stdout=(
            "9f1c\trefs/tags/1.0.0\n"
            "a2b3\trefs/tags/1.0.3\n"
            "c4d5\trefs/tags/1.0.10\n"
        ),
        captured=captured,
    )

    versions = _repository().list_available_versions("sensor_app")

    assert versions == ["1.0.10", "1.0.3", "1.0.0"]
    assert captured[0][:2] == ["git", "-c"]
    assert "ls-remote" in captured[0]
    assert captured[0][-1].endswith("/dsm-src/sensor_app.git")


def test_branch_refs_are_not_offered_as_versions(monkeypatch):
    """Versions are tags. A branch is a moving ref, and the produced file
    records the version string it was given (req 14), so offering one would
    put a name whose contents can change afterwards into the artifact."""
    _fake_git(
        monkeypatch,
        stdout=(
            "9f1c\trefs/heads/main\n"
            "a2b3\trefs/heads/release-1.1\n"
            "c4d5\trefs/tags/1.0.0\n"
        ),
    )

    assert _repository().list_available_versions("sensor_app") == ["1.0.0"]


def test_a_unit_with_no_published_versions_lists_empty(monkeypatch):
    """Not an error: a repository that exists but has published nothing simply
    offers no candidate."""
    _fake_git(monkeypatch, stdout="")

    assert _repository().list_available_versions("sensor_app") == []


def test_listing_versions_maps_an_auth_failure_to_the_auth_error(monkeypatch):
    _fake_git(monkeypatch, returncode=128, stderr="fatal: Authentication failed for 'http://gitea:3000'")

    with pytest.raises(SourceRepoAuthError, match="sensor_app"):
        _repository().list_available_versions("sensor_app")


def test_listing_versions_maps_any_other_failure_to_the_access_error(monkeypatch):
    _fake_git(monkeypatch, returncode=128, stderr="fatal: repository not found")

    with pytest.raises(SourceRepoAccessError, match="repository not found"):
        _repository().list_available_versions("sensor_app")


# --------------------------------------------------------------- scan

VALID_MAKEFILE = "include include/Makefile_java.mk\n"
INVALID_MAKEFILE = "all:\n\techo build\n"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _scan(unit_dir: Path) -> list:
    return _repository().scan_cloned_unit(SoftwareUnitVersion("nav_app", "1.0.0"), unit_dir)


def test_scan_records_a_root_makefile_and_topic_manifest(tmp_path: Path):
    _write(tmp_path / "Makefile", VALID_MAKEFILE)
    _write(tmp_path / "src" / "nav_app.xml", "<manifest/>")

    records = _scan(tmp_path)

    assert {(f.file_name, f.status) for f in records} == {
        ("Makefile", AcquisitionStatus.OK),
        ("nav_app.xml", AcquisitionStatus.OK),
    }
    assert {f.file_path for f in records} == {
        str(tmp_path / "Makefile"),
        str(tmp_path / "src" / "nav_app.xml"),
    }


def test_scan_finds_nested_makefile_and_nested_topic_manifest(tmp_path: Path):
    """The run itself reads these files — the build runner rglobs for the
    Makefile and the analyzer globs under src/ — so the scan must record them
    as OK at the path found, not as missing at a fixed path."""
    _write(tmp_path / "build" / "Makefile", VALID_MAKEFILE)
    _write(tmp_path / "src" / "sub" / "nav_app.xml", "<manifest/>")

    records = {f.file_name: f for f in _scan(tmp_path)}

    assert set(records) == {"Makefile", "nav_app.xml"}
    assert records["Makefile"].file_path == str(tmp_path / "build" / "Makefile")
    assert records["nav_app.xml"].file_path == str(tmp_path / "src" / "sub" / "nav_app.xml")
    assert all(f.status == AcquisitionStatus.OK for f in records.values())


def test_scan_ignores_a_makefile_without_a_configured_include(tmp_path: Path):
    """Content check, not just a name: an invalid Makefile is treated as not
    found, and the generate step then records it as MISSING_DATA."""
    _write(tmp_path / "build" / "Makefile", INVALID_MAKEFILE)
    _write(tmp_path / "src" / "nav_app.xml", "<manifest/>")

    records = _scan(tmp_path)

    assert {(f.file_name, f.status) for f in records} == {
        ("nav_app.xml", AcquisitionStatus.OK),
    }


def test_scan_records_only_the_first_matching_topic_manifest(tmp_path: Path):
    """The analyzer parses matches[0] of the same sorted glob, so the record
    must name that file — duplicates deeper in the tree are not acquired."""
    _write(tmp_path / "src" / "a" / "nav_app.xml", "<manifest/>")
    _write(tmp_path / "src" / "b" / "nav_app.xml", "<manifest/>")

    records = [f for f in _scan(tmp_path) if f.file_name == "nav_app.xml"]

    assert [f.file_path for f in records] == [str(tmp_path / "src" / "a" / "nav_app.xml")]


def test_scan_records_nothing_when_nothing_is_present(tmp_path: Path):
    _write(tmp_path / "src" / "other.xml", "<manifest/>")

    assert _scan(tmp_path) == []
