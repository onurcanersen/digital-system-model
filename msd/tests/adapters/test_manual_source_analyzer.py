"""Tests for ManualSourceAnalyzer (SRS DSM-MSD req 13, 19) using
self-contained tmp_path fixtures. The CodeQL strategy is excluded from msd,
so only the manual XML/import strategy is covered.

Covers the configurable behaviors: the topic manifest is named
src/<folder_name>.xml (not a fixed name), only imports ending in a
configured suffix count as "uses" dependencies, dummy-topic names are
filtered out, and custom_topic_name selects the XML element — all sourced
from msd.ini via adapters/config.py.
"""

from pathlib import Path

import pytest

from adapters.analysis.manual_source_analyzer import ManualSourceAnalyzer
from adapters.config import ENV_OVERRIDE_VAR, get_config


@pytest.fixture(autouse=True)
def _clear_config_cache():
    get_config.cache_clear()
    yield
    get_config.cache_clear()


def _write_config(tmp_path: Path, monkeypatch, ini_body: str) -> None:
    config_path = tmp_path / "runtime.ini"
    config_path.write_text(ini_body, encoding="utf-8")
    monkeypatch.setenv(ENV_OVERRIDE_VAR, str(config_path))
    get_config.cache_clear()


def _write_unit(tmp_path: Path, folder_name: str, xml_body: str, java_imports: str = "") -> Path:
    folder = tmp_path / folder_name
    (folder / "src").mkdir(parents=True)
    (folder / "src" / f"{folder_name}.xml").write_text(xml_body, encoding="utf-8")
    if java_imports:
        (folder / f"{folder_name.title()}.java").write_text(
            f"package a.b.c.{folder_name};\n{java_imports}\npublic class X {{}}\n", encoding="utf-8"
        )
    return folder


def test_extract_finds_pub_and_sub_topics_from_named_manifest(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, "[analyzer]\nimport_domain_prefix = a.b.c\ndependency_suffixes = _lib\n")
    folder = _write_unit(
        tmp_path, "nav_app",
        '<unit><topic name="nav_position" role="pub"/><topic name="sensor_data" role="sub"/></unit>',
    )

    entries = ManualSourceAnalyzer().extract(folder, "nav_app")

    roles = {(e.name, e.role) for e in entries}
    assert ("nav_position", "pub") in roles
    assert ("sensor_data", "sub") in roles


def test_extract_finds_manifest_nested_deeper_than_directly_under_src(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, "[analyzer]\n")
    folder = tmp_path / "nav_app"
    (folder / "src" / "generated").mkdir(parents=True)
    (folder / "src" / "generated" / "nav_app.xml").write_text(
        '<unit><topic name="nav_position" role="pub"/></unit>', encoding="utf-8"
    )

    entries = ManualSourceAnalyzer().extract(folder, "nav_app")

    assert ("nav_position", "pub") in {(e.name, e.role) for e in entries}


def test_extract_does_not_find_manifest_named_after_something_else(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, "[analyzer]\n")
    folder = tmp_path / "nav_app"
    (folder / "src").mkdir(parents=True)
    (folder / "src" / "unit.xml").write_text('<unit><topic name="x" role="pub"/></unit>', encoding="utf-8")

    entries = ManualSourceAnalyzer().extract(folder, "nav_app")

    assert entries == []


def test_extract_finds_uses_dependency_ending_in_configured_suffix(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, "[analyzer]\nimport_domain_prefix = a.b.c\ndependency_suffixes = _lib\n")
    folder = _write_unit(
        tmp_path, "nav_app", "<unit></unit>",
        java_imports="import a.b.c.common_lib.Utils;",
    )

    entries = ManualSourceAnalyzer().extract(folder, "nav_app")

    assert ("common_lib", "uses") in {(e.name, e.role) for e in entries}


def test_extract_excludes_import_not_matching_configured_suffix(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, "[analyzer]\nimport_domain_prefix = a.b.c\ndependency_suffixes = _lib\n")
    folder = _write_unit(
        tmp_path, "nav_app", "<unit></unit>",
        java_imports="import a.b.c.common_utils.Helper;",
    )

    entries = ManualSourceAnalyzer().extract(folder, "nav_app")

    assert entries == []


def test_extract_skips_dummy_topics(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, "[analyzer]\ndummy_topic_names = DummyTopic\n")
    folder = _write_unit(
        tmp_path, "nav_app",
        '<unit><topic name="DummyTopic" role="pub"/><topic name="real_topic" role="pub"/></unit>',
    )

    entries = ManualSourceAnalyzer().extract(folder, "nav_app")

    names = {e.name for e in entries}
    assert "DummyTopic" not in names
    assert "real_topic" in names


def test_extract_uses_configured_custom_topic_name(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, "[analyzer]\ncustom_topic_name = mytopic\n")
    folder = _write_unit(
        tmp_path, "nav_app",
        '<unit><mytopic name="t1" role="pub"/><topic name="ignored" role="pub"/></unit>',
    )

    entries = ManualSourceAnalyzer().extract(folder, "nav_app")

    roles = {(e.name, e.role) for e in entries}
    assert ("t1", "pub") in roles
    assert "ignored" not in {e.name for e in entries}


def test_extract_returns_empty_list_when_no_manifest_or_imports(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, "[analyzer]\n")
    folder = tmp_path / "empty_unit"
    folder.mkdir()

    entries = ManualSourceAnalyzer().extract(folder, "empty_unit")

    assert entries == []
