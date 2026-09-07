"""Tests for ManualSourceAnalyzer (SRS DSM-MSD req 13, 19) using
self-contained tmp_path fixtures. The CodeQL strategy is excluded from msd,
so only the manual XML/import strategy is covered.

Covers the configurable behaviors: the topic manifest is named
src/<folder_name>.xml (not a fixed name), only imports ending in a
configured suffix count as "uses" dependencies, dummy-topic names are
filtered out, and custom_topic_name selects the XML element — the settings
come from an explicitly constructed AnalyzerConfig.
"""

from pathlib import Path

from msd.adapters.analysis.manual_source_analyzer import ManualSourceAnalyzer
from msd.config import AnalyzerConfig
from msd.domain.extracted_topic import TopicRole


def _analyzer(**kwargs) -> ManualSourceAnalyzer:
    return ManualSourceAnalyzer(AnalyzerConfig(**kwargs))


def _write_unit(tmp_path: Path, folder_name: str, xml_body: str, java_imports: str = "") -> Path:
    folder = tmp_path / folder_name
    (folder / "src").mkdir(parents=True)
    (folder / "src" / f"{folder_name}.xml").write_text(xml_body, encoding="utf-8")
    if java_imports:
        (folder / f"{folder_name.title()}.java").write_text(
            f"package a.b.c.{folder_name};\n{java_imports}\npublic class X {{}}\n", encoding="utf-8"
        )
    return folder


def test_extract_finds_pub_and_sub_topics_from_named_manifest(tmp_path):
    folder = _write_unit(
        tmp_path, "nav_app",
        '<unit><topic name="nav_position" role="pub"/><topic name="sensor_data" role="sub"/></unit>',
    )

    entries = _analyzer(import_domain_prefix="a.b.c", dependency_suffixes=["_lib"]).extract(folder, "nav_app")

    roles = {(e.name, e.role) for e in entries}
    assert ("nav_position", TopicRole.PUB) in roles
    assert ("sensor_data", TopicRole.SUB) in roles


def test_extract_finds_manifest_nested_deeper_than_directly_under_src(tmp_path):
    folder = tmp_path / "nav_app"
    (folder / "src" / "generated").mkdir(parents=True)
    (folder / "src" / "generated" / "nav_app.xml").write_text(
        '<unit><topic name="nav_position" role="pub"/></unit>', encoding="utf-8"
    )

    entries = _analyzer().extract(folder, "nav_app")

    assert ("nav_position", TopicRole.PUB) in {(e.name, e.role) for e in entries}


def test_extract_does_not_find_manifest_named_after_something_else(tmp_path):
    folder = tmp_path / "nav_app"
    (folder / "src").mkdir(parents=True)
    (folder / "src" / "unit.xml").write_text('<unit><topic name="x" role="pub"/></unit>', encoding="utf-8")

    entries = _analyzer().extract(folder, "nav_app")

    assert entries == []


def test_extract_finds_uses_dependency_ending_in_configured_suffix(tmp_path):
    folder = _write_unit(
        tmp_path, "nav_app", "<unit></unit>",
        java_imports="import a.b.c.common_lib.Utils;",
    )

    entries = _analyzer(import_domain_prefix="a.b.c", dependency_suffixes=["_lib"]).extract(folder, "nav_app")

    assert ("common_lib", TopicRole.USES) in {(e.name, e.role) for e in entries}


def test_extract_excludes_import_not_matching_configured_suffix(tmp_path):
    folder = _write_unit(
        tmp_path, "nav_app", "<unit></unit>",
        java_imports="import a.b.c.common_utils.Helper;",
    )

    entries = _analyzer(import_domain_prefix="a.b.c", dependency_suffixes=["_lib"]).extract(folder, "nav_app")

    assert entries == []


def test_extract_skips_dummy_topics(tmp_path):
    folder = _write_unit(
        tmp_path, "nav_app",
        '<unit><topic name="DummyTopic" role="pub"/><topic name="real_topic" role="pub"/></unit>',
    )

    entries = _analyzer(dummy_topic_names=["DummyTopic"]).extract(folder, "nav_app")

    names = {e.name for e in entries}
    assert "DummyTopic" not in names
    assert "real_topic" in names


def test_extract_uses_configured_custom_topic_name(tmp_path):
    folder = _write_unit(
        tmp_path, "nav_app",
        '<unit><mytopic name="t1" role="pub"/><topic name="ignored" role="pub"/></unit>',
    )

    entries = _analyzer(custom_topic_name="mytopic").extract(folder, "nav_app")

    roles = {(e.name, e.role) for e in entries}
    assert ("t1", TopicRole.PUB) in roles
    assert "ignored" not in {e.name for e in entries}


def test_extract_skips_topics_with_unknown_roles(tmp_path):
    folder = _write_unit(
        tmp_path, "nav_app",
        '<unit><topic name="real_topic" role="pub"/><topic name="weird_topic" role="broadcast"/></unit>',
    )

    entries = _analyzer().extract(folder, "nav_app")

    names = {e.name for e in entries}
    assert "weird_topic" not in names
    assert "real_topic" in names


def test_extract_returns_empty_list_when_no_manifest_or_imports(tmp_path):
    folder = tmp_path / "empty_unit"
    folder.mkdir()

    entries = _analyzer().extract(folder, "empty_unit")

    assert entries == []
