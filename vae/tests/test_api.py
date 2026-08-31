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
    assert "Digital System Model" in resp.text
    assert "Login" in resp.text


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


def test_units_endpoint_returns_selection_units():
    client = _client()
    _login(client)
    _connect_data_sources(client)

    resp = client.get("/api/projects/proj-1/platforms/plat-1/versions/1.0.0/units")

    assert resp.status_code == 200
    assert resp.get_json()["units"] == [
        {"unit_name": "unit-alpha", "version": "1.0.0", "is_candidate": False},
        {"unit_name": "unit-beta", "version": "2.1.0", "is_candidate": False},
    ]


def test_units_endpoint_only_requires_config_mgmt_db_not_source_repo():
    client = _client()
    _login(client)
    resp = _connect_config_mgmt_db(client)
    assert resp.status_code == 200

    resp = client.get("/api/projects/proj-1/platforms/plat-1/versions/1.0.0/units")

    assert resp.status_code == 200


def test_units_endpoint_requires_login_and_config_db():
    client = _client()

    resp = client.get("/api/projects/proj-1/platforms/plat-1/versions/1.0.0/units")
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "authentication required"}

    _login(client)
    resp = client.get("/api/projects/proj-1/platforms/plat-1/versions/1.0.0/units")
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "config management database connection required"}


def test_run_returns_task_id():
    client = _client()
    _login(client)
    _connect_data_sources(client)

    resp = client.post("/api/msd/run", json=SELECTION)
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["task_id"]


def test_cancel_queued_task_reports_revoked():
    client = _client()
    _login(client)  # no data source connections needed for a broker op

    resp = client.post("/api/msd/tasks/does-not-exist/cancel")

    assert resp.status_code == 200
    assert resp.get_json() == {"task_id": "does-not-exist", "state": "REVOKED"}


def test_cancel_completed_task_reports_its_final_state():
    client = _client()
    _login(client)
    _connect_data_sources(client)

    task_id = client.post("/api/msd/run", json=SELECTION).get_json()["task_id"]
    resp = client.post(f"/api/msd/tasks/{task_id}/cancel")

    assert resp.status_code == 200
    assert resp.get_json()["state"] == "SUCCESS"


def test_cancel_requires_login():
    resp = _client().post("/api/msd/tasks/does-not-exist/cancel")

    assert resp.status_code == 401
    assert resp.get_json() == {"error": "authentication required"}


def test_cancel_failure_maps_to_502():
    class _BrokenCancelRunner(FakeTaskRunner):
        def cancel(self, task_id):
            raise RuntimeError("broker down")

    components = Components(
        defaults=_DEFAULTS,
        config_repo_factory=lambda ds: FakeConfigManagementRepository(),
        msd_task_runner=_BrokenCancelRunner(run=lambda **ids: None),
        auth_repo=InMemoryLdapAuthRepository(),
    )
    client = _client(components)
    _login(client)

    resp = client.post("/api/msd/tasks/does-not-exist/cancel")

    assert resp.status_code == 502
    assert "broker down" in resp.get_json()["error"]


def _completed_task_id(components: Components, client) -> str:
    _connect_data_sources(client)
    return client.post("/api/msd/run", json=SELECTION).get_json()["task_id"]


def test_output_stream_serves_lines_and_done():
    components = _components()
    client = _client(components)
    _login(client)
    task_id = _completed_task_id(components, client)
    components.task_output_store.append(task_id, "clone: nav_app 1.0.0 cloned to /ws")
    components.task_output_store.append(task_id, "generate: wrote model setup data to /ws/model_setup_data.json")

    resp = client.get(f"/api/msd/tasks/{task_id}/output")

    assert resp.status_code == 200
    assert resp.content_type.startswith("text/event-stream")
    body = resp.get_data(as_text=True)
    assert "data: clone: nav_app 1.0.0 cloned to /ws" in body
    assert "data: generate: wrote model setup data to /ws/model_setup_data.json" in body
    assert "event: status" in body
    done = body.index("event: done")
    assert '"state": "SUCCESS"' in body[done:]
    assert '"selection"' in body[done:]  # terminal payload carries the result


def test_output_stream_emits_status_on_state_changes():
    components = Components(
        defaults=_DEFAULTS,
        config_repo_factory=lambda ds: FakeConfigManagementRepository(),
        msd_task_runner=FakeTaskRunner(
            run=lambda **ids: {"selection": {k: ids[k] for k in SELECTION}},
            state_sequence=["PENDING", "STARTED"],
        ),
        auth_repo=InMemoryLdapAuthRepository(),
    )
    client = _client(components)
    _login(client)
    task_id = _completed_task_id(components, client)

    resp = client.get(f"/api/msd/tasks/{task_id}/output")

    body = resp.get_data(as_text=True)
    pending = body.index('"state": "PENDING"')
    started = body.index('"state": "STARTED"')
    done = body.index("event: done")
    assert pending < started < done
    assert '"state": "SUCCESS"' in body[done:]
    assert '"selection"' in body[done:]  # terminal payload carries the result


def test_output_stream_resumes_from_last_event_id():
    components = _components()
    client = _client(components)
    _login(client)
    task_id = _completed_task_id(components, client)
    for line in ("line one", "line two", "line three"):
        components.task_output_store.append(task_id, line)

    resp = client.get(f"/api/msd/tasks/{task_id}/output", headers={"Last-Event-ID": "1"})

    body = resp.get_data(as_text=True)
    assert "line one" not in body
    assert "data: line two" in body
    assert "data: line three" in body
    assert "event: status" in body  # state re-sent as a snapshot on reconnect
    assert "event: done" in body


def test_output_stream_requires_login():
    resp = _client().get("/api/msd/tasks/does-not-exist/output")

    assert resp.status_code == 401
    assert resp.get_json() == {"error": "authentication required"}


def test_download_serves_the_generated_json(tmp_path):
    out = tmp_path / "model_setup_data.json"
    out.write_text('{"apps": 2}')
    components = Components(
        defaults=_DEFAULTS,
        config_repo_factory=lambda ds: FakeConfigManagementRepository(),
        msd_task_runner=FakeTaskRunner(run=lambda **ids: {"output_path": str(out)}),
        auth_repo=InMemoryLdapAuthRepository(),
    )
    client = _client(components)
    _login(client)
    _connect_data_sources(client)
    task_id = client.post("/api/msd/run", json=SELECTION).get_json()["task_id"]

    resp = client.get(f"/api/msd/tasks/{task_id}/download")

    assert resp.status_code == 200
    assert resp.content_type == "application/json"
    assert "attachment" in resp.headers["Content-Disposition"]
    assert "model_setup_data.json" in resp.headers["Content-Disposition"]
    assert resp.get_json() == {"apps": 2}


def test_download_requires_login():
    resp = _client().get("/api/msd/tasks/does-not-exist/download")

    assert resp.status_code == 401
    assert resp.get_json() == {"error": "authentication required"}


def test_download_without_run_output_reports_404():
    client = _client()
    _login(client)

    resp = client.get("/api/msd/tasks/does-not-exist/download")

    assert resp.status_code == 404
    assert resp.get_json() == {"error": "run has no output file"}


def test_download_missing_file_reports_404(tmp_path):
    components = Components(
        defaults=_DEFAULTS,
        config_repo_factory=lambda ds: FakeConfigManagementRepository(),
        msd_task_runner=FakeTaskRunner(run=lambda **ids: {"output_path": str(tmp_path / "gone.json")}),
        auth_repo=InMemoryLdapAuthRepository(),
    )
    client = _client(components)
    _login(client)
    _connect_data_sources(client)
    task_id = client.post("/api/msd/run", json=SELECTION).get_json()["task_id"]

    resp = client.get(f"/api/msd/tasks/{task_id}/download")

    assert resp.status_code == 404
    assert resp.get_json() == {"error": "output file not found"}


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


def test_units_access_error_maps_to_502():
    class _BrokenUnitsRepo(FakeConfigManagementRepository):
        def list_unit_versions(self, project_id, platform_id, version_id):
            raise ConfigManagementAccessError("config db down")

    components = Components(
        defaults=_DEFAULTS,
        config_repo_factory=lambda ds: _BrokenUnitsRepo(),
        msd_task_runner=FakeTaskRunner(run=lambda **ids: None),
        auth_repo=InMemoryLdapAuthRepository(),
    )
    client = _client(components)
    _login(client)
    _connect_data_sources(client)

    resp = client.get("/api/projects/proj-1/platforms/plat-1/versions/1.0.0/units")

    assert resp.status_code == 502
    assert "config db down" in resp.get_json()["error"]


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


def test_session_reports_unauthenticated():
    resp = _client().get("/api/session")

    assert resp.status_code == 200
    assert resp.get_json() == {"authenticated": False}


def test_session_reports_connection_state_and_empty_persistence():
    client = _client()
    _login(client)
    _connect_data_sources(client)

    body = client.get("/api/session").get_json()

    assert body["authenticated"] is True
    assert body["username"] == "admin"
    assert body["role"] == "admin"
    assert body["defaults"] == {
        "config_mgmt_db": "localhost:3306/cmdb",
        "source_code_repo": "http://localhost:3001/dsm-src",
    }
    assert body["config_mgmt_db_connected"] is True
    assert body["source_code_repo_connected"] is True
    assert body["selection"] is None
    assert body["active_task"] is None


def test_set_selection_requires_login_and_config_db():
    client = _client()

    resp = client.post("/api/selection", json=SELECTION)
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "authentication required"}

    _login(client)
    resp = client.post("/api/selection", json=SELECTION)
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "config management database connection required"}


def test_set_selection_validates_body():
    client = _client()
    _login(client)
    _connect_config_mgmt_db(client)

    resp = client.post("/api/selection", json={"project_id": "proj-1"})
    assert resp.status_code == 400
    assert "missing field" in resp.get_json()["error"]

    resp = client.post("/api/selection", data=b"not json", content_type="application/json")
    assert resp.status_code == 400


def test_set_selection_is_reflected_in_session():
    client = _client()
    _login(client)
    _connect_data_sources(client)

    resp = client.post("/api/selection", json=SELECTION)
    assert resp.status_code == 200
    assert resp.get_json() == {"selection": SELECTION}

    assert client.get("/api/session").get_json()["selection"] == SELECTION


def test_delete_selection_clears_it():
    client = _client()
    _login(client)
    _connect_data_sources(client)
    client.post("/api/selection", json=SELECTION)

    resp = client.delete("/api/selection")
    assert resp.status_code == 204

    assert client.get("/api/session").get_json()["selection"] is None


def test_reconnecting_config_mgmt_db_clears_selection():
    client = _client()
    _login(client)
    _connect_data_sources(client)
    client.post("/api/selection", json=SELECTION)

    resp = _connect_config_mgmt_db(client)
    assert resp.status_code == 200

    body = client.get("/api/session").get_json()
    assert body["selection"] is None
    assert body["source_code_repo_connected"] is False  # a new config-DB connection starts fresh


def test_run_sets_active_task_in_session():
    client = _client()
    _login(client)
    _connect_data_sources(client)

    task_id = client.post("/api/msd/run", json=SELECTION).get_json()["task_id"]

    active_task = client.get("/api/session").get_json()["active_task"]
    assert active_task["task_id"] == task_id
    assert active_task["project_id"] == SELECTION["project_id"]
    assert active_task["platform_id"] == SELECTION["platform_id"]
    assert active_task["version_id"] == SELECTION["version_id"]
    assert active_task["submitted_at"] > 0


def test_new_run_overwrites_active_task():
    client = _client()
    _login(client)
    _connect_data_sources(client)

    client.post("/api/msd/run", json=SELECTION)
    second = client.post("/api/msd/run", json=SELECTION).get_json()["task_id"]

    assert client.get("/api/session").get_json()["active_task"]["task_id"] == second


def test_stale_active_task_is_dropped_from_session():
    from vae.worker import RESULT_EXPIRES_SECONDS

    client = _client()
    _login(client)
    _connect_data_sources(client)
    client.post("/api/msd/run", json=SELECTION)
    with client.session_transaction() as sess:
        sess["active_task"]["submitted_at"] -= RESULT_EXPIRES_SECONDS + 1
        sess.modified = True  # nested mutation doesn't flag the session itself

    body = client.get("/api/session").get_json()
    assert body["active_task"] is None
    with client.session_transaction() as sess:
        assert "active_task" not in sess


def test_logout_clears_selection_and_active_task():
    client = _client()
    _login(client)
    _connect_data_sources(client)
    client.post("/api/selection", json=SELECTION)
    client.post("/api/msd/run", json=SELECTION)

    resp = client.post("/api/logout")
    assert resp.status_code == 204

    _login(client)
    body = client.get("/api/session").get_json()
    assert body["selection"] is None
    assert body["active_task"] is None
