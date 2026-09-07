import pytest

from msd.config import get_config, load_config


@pytest.fixture(autouse=True)
def _clear_cache():
    get_config.cache_clear()
    yield
    get_config.cache_clear()


def test_loads_analyzer_section_from_default_msd_ini():
    config = get_config()

    assert config.analyzer.import_domain_prefix == "a.b.c"
    assert config.analyzer.dependency_suffixes == ["_lib"]
    assert config.analyzer.dummy_topic_names == ["DummyTopic"]
    assert config.analyzer.makefile_include_patterns == ["include/Makefile_java.mk"]
    assert config.analyzer.custom_topic_name == "topic"
    assert config.analyzer.run_build is False


def test_loads_workspace_section_from_default_msd_ini():
    config = get_config()

    assert config.workspace.path == "workspace"


def test_run_build_can_be_toggled_on_via_runtime_ini(tmp_path):
    override_path = tmp_path / "custom_runtime.ini"
    override_path.write_text("[analyzer]\nrun_build = true\n", encoding="utf-8")

    config = load_config(override_path)

    assert config.analyzer.run_build is True


def test_load_config_reads_an_explicit_path(tmp_path):
    override_path = tmp_path / "custom_runtime.ini"
    override_path.write_text(
        "[analyzer]\nimport_domain_prefix = x.y.z\ndependency_suffixes = _module\n",
        encoding="utf-8",
    )

    config = load_config(override_path)

    assert config.analyzer.import_domain_prefix == "x.y.z"
    assert config.analyzer.dependency_suffixes == ["_module"]


def test_runtime_ini_can_override_workspace(tmp_path):
    override_path = tmp_path / "custom_runtime.ini"
    override_path.write_text("[workspace]\npath = /custom/ws\n", encoding="utf-8")

    config = load_config(override_path)

    assert config.workspace.path == "/custom/ws"


def test_missing_file_returns_empty_defaults(tmp_path):
    config = load_config(tmp_path / "does_not_exist.ini")

    assert config.analyzer.dummy_topic_names == []
    assert config.analyzer.import_domain_prefix == ""
    assert config.analyzer.run_build is False
    assert config.workspace.path == "workspace"


