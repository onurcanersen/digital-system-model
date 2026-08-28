import pytest

from config import get_config, load_config
from domain.data_source import SourceType


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


def test_loads_workspace_api_worker_sections_from_default_msd_ini():
    config = get_config()

    assert config.workspace.path == "workspace"
    assert config.api.host == "127.0.0.1"
    assert config.api.port == 8080
    assert config.worker.broker_url == "redis://localhost:6379/0"
    assert config.worker.result_backend == "redis://localhost:6379/1"


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


def test_runtime_ini_can_override_workspace_api_worker(tmp_path):
    override_path = tmp_path / "custom_runtime.ini"
    override_path.write_text(
        "[workspace]\npath = /custom/ws\n"
        "\n"
        "[api]\nhost = 0.0.0.0\nport = 9090\n"
        "\n"
        "[worker]\nbroker_url = redis://broker:6380/2\nresult_backend = redis://backend:6380/3\n",
        encoding="utf-8",
    )

    config = load_config(override_path)

    assert config.workspace.path == "/custom/ws"
    assert config.api.host == "0.0.0.0"
    assert config.api.port == 9090
    assert config.worker.broker_url == "redis://broker:6380/2"
    assert config.worker.result_backend == "redis://backend:6380/3"


def test_missing_file_returns_empty_defaults(tmp_path):
    config = load_config(tmp_path / "does_not_exist.ini")

    assert config.analyzer.dummy_topic_names == []
    assert config.analyzer.import_domain_prefix == ""
    assert config.analyzer.run_build is False
    assert config.data_sources == []
    assert config.workspace.path == "workspace"
    assert config.api.host == "127.0.0.1"
    assert config.api.port == 8080
    assert config.worker.broker_url == "redis://localhost:6379/0"
    assert config.worker.result_backend == "redis://localhost:6379/1"


def test_returns_only_data_sources_from_merged_file(tmp_path):
    path = tmp_path / "config.ini"
    path.write_text(
        "[config_mgmt_db]\n"
        "source_name = mysql\n"
        "access_method = mysql\n"
        "connection_address = localhost:3306/cmdb\n"
        "user_info = dsm:dsm\n"
        "\n"
        "[source_code_repo]\n"
        "source_name = gitea\n"
        "access_method = git\n"
        "connection_address = http://localhost:3001/dsm-src\n"
        "user_info = dsm:dsm\n"
        "\n"
        "[analyzer]\n"
        "custom_topic_name = topic\n"
        "run_build = false\n",
        encoding="utf-8",
    )

    loaded = load_config(path).data_sources

    assert [c.source_name for c in loaded] == ["mysql", "gitea"]
    assert loaded[0].source_type.value == "config_mgmt_db"
    assert loaded[0].connection_address == "localhost:3306/cmdb"
    assert loaded[1].source_type.value == "source_code_repo"
    assert loaded[1].user_info == "dsm:dsm"


def test_ignores_sections_that_are_not_data_sources(tmp_path):
    path = tmp_path / "config.ini"
    path.write_text(
        "[analyzer]\ncustom_topic_name = topic\n"
        "\n"
        "[workspace]\npath = workspace\n"
        "\n"
        "[api]\nhost = 127.0.0.1\nport = 8080\n"
        "\n"
        "[worker]\nbroker_url = redis://localhost:6379/0\nresult_backend = redis://localhost:6379/1\n",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.data_sources == []
    assert config.workspace.path == "workspace"
    assert config.api.port == 8080
    assert config.worker.broker_url == "redis://localhost:6379/0"
