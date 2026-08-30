"""Tests for VAE's Flask API (SRS DSM-VAE req 4-6, minimal slice): selection
is synchronous, triggering + monitoring an MSD run is delegated to a fake
ITaskRunner in-process, so no broker/DB is needed."""

from fakes.fake_config_management_repository import FakeConfigManagementRepository
from fakes.fake_task_runner import FakeTaskRunner

from vae.adapters.in_memory_ldap_auth_repository import InMemoryLdapAuthRepository
from vae.api import create_app
from vae.composition import Components

from msd.domain.data_source import DataSourceConfig, SourceType
from msd.ports.config_management_repository import ConfigManagementAccessError

SELECTION = {"project_id": "proj-1", "platform_id": "plat-1", "version_id": "1.0.0"}

_DEFAULTS = {
    SourceType.CONFIG_MGMT_DB: DataSourceConfig(
        SourceType.CONFIG_MGMT_DB, "mysql", "mysql", "localhost:3306/cmdb", ""
    ),
    SourceType.SOURCE_CODE_REPO: DataSourceConfig(
        SourceType.SOURCE_CODE_REPO, "gitea", "git", "http://localhost:3001/dsm-src", ""
    ),
}


def _components(**config_repo_kwargs) -> Components:
    return Components(
        defaults=_DEFAULTS,
        config_repo_factory=lambda ds: FakeConfigManagementRepository(**config_repo_kwargs),
        msd_task_runner=FakeTaskRunner(run=lambda **ids: {"selection": {k: ids[k] for k in SELECTION}}),
        auth_repo=InMemoryLdapAuthRepository(),
    )


def _client(components: Components = None):
    return create_app(components or _components()).test_client()


def _login(client, username="admin", password="admin"):
    resp = client.post("/api/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    return resp


def _connect_config_mgmt_db(client, connection_address="localhost:3306/cmdb", username="dsm", password="dsm"):
    return client.post(
        "/api/data-sources/connect/config-mgmt-db",
        json={"connection_address": connection_address, "username": username, "password": password},
    )


def _connect_source_repo(client, connection_address="http://localhost:3001/dsm-src", username="dsm", password="dsm"):
    return client.post(
        "/api/data-sources/connect/source-code-repo",
        json={"connection_address": connection_address, "username": username, "password": password},
    )


def _connect_data_sources(client, **kwargs):
    resp = _connect_config_mgmt_db(client, **kwargs)
    assert resp.status_code == 200
    resp = _connect_source_repo(client, **kwargs)
    assert resp.status_code == 200
    return resp


def test_index_serves_the_ui():
    resp = _client().get("/")

    assert resp.status_code == 200
    assert "Design Verification" in resp.text
    assert "Sign in" in resp.text


def test_login_response_includes_data_source_defaults():
    resp = _client().post("/api/login", json={"username": "admin", "password": "admin"})

    assert resp.status_code == 200
    assert resp.get_json()["defaults"] == {
        "config_mgmt_db": "localhost:3306/cmdb",
        "source_code_repo": "http://localhost:3001/dsm-src",
    }


def test_selection_endpoints():
    client = _client()
    _login(client)
    _connect_data_sources(client)

    resp = client.get("/api/projects")
    assert resp.status_code == 200
    assert resp.get_json()["projects"][0]["project_id"] == "proj-1"

    resp = client.get("/api/projects/proj-1/platforms")
    assert resp.status_code == 200
    assert resp.get_json()["platforms"][0]["platform_id"] == "plat-1"

    resp = client.get("/api/projects/proj-1/platforms/plat-1/versions")
    assert resp.status_code == 200
    assert resp.get_json()["versions"][0]["is_effective"] is True


def test_selection_endpoints_only_require_config_mgmt_db_not_source_repo():
    client = _client()
    _login(client)
    resp = _connect_config_mgmt_db(client)
    assert resp.status_code == 200

    resp = client.get("/api/projects")

    assert resp.status_code == 200


def test_run_and_status_round_trip():
    client = _client()
    _login(client)
    _connect_data_sources(client)

    resp = client.post("/api/msd/run", json=SELECTION)
    assert resp.status_code == 202
    body = resp.get_json()
    task_id = body["task_id"]
    assert task_id
    assert body["status_url"] == f"/api/msd/tasks/{task_id}"

    status = client.get(f"/api/msd/tasks/{task_id}").get_json()
    assert status["state"] == "SUCCESS"
    assert status["result"]["selection"] == SELECTION


def test_unknown_task_id_reports_pending():
    client = _client()
    _login(client)
    _connect_data_sources(client)

    resp = client.get("/api/msd/tasks/does-not-exist")

    assert resp.status_code == 200
    assert resp.get_json() == {"task_id": "does-not-exist", "state": "PENDING"}


def test_selection_body_validation():
    client = _client()
    _login(client)
    _connect_data_sources(client)

    resp = client.post("/api/msd/run", json={})
    assert resp.status_code == 400
    assert "missing field" in resp.get_json()["error"]

    resp = client.post("/api/msd/run", data=b"not json", content_type="application/json")
    assert resp.status_code == 400


def test_runner_submission_failure_maps_to_502():
    class _BrokenRunner(FakeTaskRunner):
        def submit_run(self, project_id, platform_id, version_id, *args, **kwargs):
            raise RuntimeError("broker down")

    components = Components(
        defaults=_DEFAULTS,
        config_repo_factory=lambda ds: FakeConfigManagementRepository(),
        msd_task_runner=_BrokenRunner(run=lambda **ids: None),
        auth_repo=InMemoryLdapAuthRepository(),
    )

    client = _client(components)
    _login(client)
    _connect_data_sources(client)
    resp = client.post("/api/msd/run", json=SELECTION)

    assert resp.status_code == 502
    assert "broker down" in resp.get_json()["error"]


def test_protected_route_without_login_is_rejected():
    resp = _client().get("/api/projects")

    assert resp.status_code == 401
    assert resp.get_json() == {"error": "authentication required"}


def test_protected_route_without_config_db_connection_is_rejected():
    client = _client()
    _login(client)

    resp = client.get("/api/projects")

    assert resp.status_code == 401
    assert resp.get_json() == {"error": "config management database connection required"}


def test_run_without_source_repo_connection_is_rejected():
    client = _client()
    _login(client)
    resp = _connect_config_mgmt_db(client)
    assert resp.status_code == 200

    resp = client.post("/api/msd/run", json=SELECTION)

    assert resp.status_code == 401
    assert resp.get_json() == {"error": "source code repo connection required"}


def test_connect_config_mgmt_db_requires_login():
    resp = _client().post(
        "/api/data-sources/connect/config-mgmt-db",
        json={"connection_address": "a", "username": "u", "password": "p"},
    )

    assert resp.status_code == 401


def test_connect_source_repo_requires_config_mgmt_db_first():
    client = _client()
    _login(client)

    resp = _connect_source_repo(client)

    assert resp.status_code == 401
    assert resp.get_json() == {"error": "config management database connection required"}


def test_connect_config_mgmt_db_failure_maps_to_502():
    client = _client(_components(raise_error=ConfigManagementAccessError("bad creds")))
    _login(client)

    resp = _connect_config_mgmt_db(client, password="wrong")

    assert resp.status_code == 502
    assert "bad creds" in resp.get_json()["error"]


def test_login_rejects_bad_credentials():
    resp = _client().post("/api/login", json={"username": "admin", "password": "wrong"})

    assert resp.status_code == 401
    assert resp.get_json() == {"error": "invalid username or password"}


def test_login_accepts_operator_role():
    resp = _client().post("/api/login", json={"username": "operator", "password": "operator"})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["username"] == "operator"
    assert body["role"] == "operator"


def test_logout_clears_the_session_and_data_source_connection():
    client = _client()
    _login(client)
    _connect_data_sources(client)
    assert client.get("/api/projects").status_code == 200

    resp = client.post("/api/logout")
    assert resp.status_code == 204

    assert client.get("/api/projects").status_code == 401

    _login(client)
    assert client.get("/api/projects").status_code == 401  # must reconnect data sources after re-login
