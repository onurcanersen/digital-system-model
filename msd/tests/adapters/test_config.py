import pytest

from adapters.config import ENV_OVERRIDE_VAR, get_config
from model.data_source import SourceType


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


def test_loads_data_source_sections_from_default_msd_ini():
    config = get_config()

    by_name = {c.source_name: c for c in config.data_sources}
    assert set(by_name) == {"gitea", "mysql"}
    assert by_name["gitea"].source_type == SourceType.SOURCE_CODE_REPO
    assert by_name["gitea"].access_method == "git"
    assert by_name["gitea"].connection_address == "http://localhost:3001/dsm-src"
    assert by_name["gitea"].user_info == "dsm:dsm"
    assert by_name["mysql"].source_type == SourceType.CONFIG_MGMT_DB
    assert by_name["mysql"].access_method == "mysql"
    assert by_name["mysql"].connection_address == "localhost:3306/cmdb"


def test_run_build_can_be_toggled_on_via_runtime_ini(tmp_path, monkeypatch):
    override_path = tmp_path / "custom_runtime.ini"
    override_path.write_text("[analyzer]\nrun_build = true\n", encoding="utf-8")
    monkeypatch.setenv(ENV_OVERRIDE_VAR, str(override_path))
    get_config.cache_clear()

    config = get_config()

    assert config.analyzer.run_build is True


def test_env_override_points_to_a_different_file(tmp_path, monkeypatch):
    override_path = tmp_path / "custom_runtime.ini"
    override_path.write_text(
        "[analyzer]\nimport_domain_prefix = x.y.z\ndependency_suffixes = _module\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(ENV_OVERRIDE_VAR, str(override_path))
    get_config.cache_clear()

    config = get_config()

    assert config.analyzer.import_domain_prefix == "x.y.z"
    assert config.analyzer.dependency_suffixes == ["_module"]


def test_missing_file_returns_empty_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_OVERRIDE_VAR, str(tmp_path / "does_not_exist.ini"))
    get_config.cache_clear()

    config = get_config()

    assert config.analyzer.dummy_topic_names == []
    assert config.analyzer.import_domain_prefix == ""
    assert config.analyzer.run_build is False
    assert config.data_sources == []


def test_returns_only_data_sources_from_merged_file(tmp_path, monkeypatch):
    path = tmp_path / "msd.ini"
    path.write_text(
        "[source_code_repo.gitea]\n"
        "access_method = git\n"
        "connection_address = http://localhost:3001/dsm-src\n"
        "user_info = dsm:dsm\n"
        "\n"
        "[config_mgmt_db.mysql]\n"
        "access_method = mysql\n"
        "connection_address = localhost:3306/cmdb\n"
        "user_info = dsm:dsm\n"
        "\n"
        "[analyzer]\n"
        "custom_topic_name = topic\n"
        "run_build = false\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(ENV_OVERRIDE_VAR, str(path))
    get_config.cache_clear()

    loaded = get_config().data_sources

    assert [c.source_name for c in loaded] == ["gitea", "mysql"]
    assert loaded[0].source_type.value == "source_code_repo"
    assert loaded[0].connection_address == "http://localhost:3001/dsm-src"
    assert loaded[1].source_type.value == "config_mgmt_db"
    assert loaded[1].user_info == "dsm:dsm"


def test_ignores_sections_that_are_not_data_sources(tmp_path, monkeypatch):
    path = tmp_path / "msd.ini"
    path.write_text("[analyzer]\ncustom_topic_name = topic\n", encoding="utf-8")
    monkeypatch.setenv(ENV_OVERRIDE_VAR, str(path))
    get_config.cache_clear()

    assert get_config().data_sources == []
