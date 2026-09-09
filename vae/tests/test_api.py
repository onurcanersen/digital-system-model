"""Tests for VAE's Flask API (SRS DSM-VAE req 4-6, minimal slice): selection
is synchronous, triggering + monitoring an MSD run is delegated to a fake
ITaskRunner in-process, so no broker/DB is needed."""

import json
from pathlib import Path

from fakes.fake_config_management_repository import FakeConfigManagementRepository
from fakes.fake_source_code_repository import FakeSourceCodeRepository
from fakes.fake_task_output_store import FakeTaskOutputStore
from fakes.fake_task_runner import FakeTaskRunner

from vae.adapters.ldap_auth_repository import LdapAuthRepository
from vae.api import create_app
from vae.composition import Components
from vae.domain.task_status import TaskStatus

from msd.adapters.filesystem_model_setup_data_catalog import FilesystemModelSetupDataCatalog
from msd.domain.data_source import DataSourceConfig, SourceType
from msd.ports.config_management_repository import ConfigManagementAccessError
from msd.ports.source_code_repository import SourceRepoAccessError

SELECTION = {"project_id": "proj-1", "platform_id": "plat-1", "version_id": "1.0.0"}

_DEFAULTS = {
    SourceType.CONFIG_MGMT_DB: DataSourceConfig(
        SourceType.CONFIG_MGMT_DB, "mysql", "mysql", "localhost:3306/cmdb", ""
    ),
    SourceType.SOURCE_CODE_REPO: DataSourceConfig(
        SourceType.SOURCE_CODE_REPO, "gitea", "git", "http://localhost:3001/dsm-src", ""
    ),
}


_UNIT_VERSIONS = {"sensor_app": ["1.0.3", "1.0.1", "1.0.0"]}


def _components(workspace=None, task_runner=None, source_repo=None, **config_repo_kwargs) -> Components:
    # The real filesystem catalog over a throwaway workspace: the artifact
    # store is a directory layout, so a fake would only restate it.
    return Components(
        defaults=_DEFAULTS,
        config_repo_factory=lambda ds: FakeConfigManagementRepository(**config_repo_kwargs),
        source_repo_factory=lambda ds: source_repo
        or FakeSourceCodeRepository(available_versions=_UNIT_VERSIONS),
        msd_task_runner=task_runner
        or FakeTaskRunner(run=lambda **ids: {"selection": {k: ids[k] for k in SELECTION}}),
        auth_repo=LdapAuthRepository(),
        task_output_store=FakeTaskOutputStore(),
        msd_catalog=FilesystemModelSetupDataCatalog(workspace or Path("/nonexistent-workspace")),
    )


def _produce(workspace: Path, run_id: str, payload: dict, selection=SELECTION) -> Path:
    """A produced file where RunWorkflow would have left it."""
    run_dir = workspace / selection["project_id"] / selection["platform_id"] / selection["version_id"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "model_setup_data.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _files_url(run_id=None, suffix="", selection=SELECTION) -> str:
    base = (
        f"/api/projects/{selection['project_id']}"
        f"/platforms/{selection['platform_id']}"
        f"/versions/{selection['version_id']}/msd-files"
    )
    return f"{base}/{run_id}{suffix}" if run_id else base


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
    assert 'id="login-form"' in resp.text


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


def test_unit_versions_lists_what_the_source_repository_publishes():
    """SRS DSM-MSD req 11: the set a candidate version is chosen from comes
    from the source repository, since no system version defines it yet."""
    client = _client()
    _login(client)
    _connect_data_sources(client)

    resp = client.get("/api/units/sensor_app/versions")

    assert resp.status_code == 200
    assert resp.get_json() == {"versions": ["1.0.3", "1.0.1", "1.0.0"]}


def test_unit_versions_is_empty_for_a_unit_that_published_none():
    client = _client()
    _login(client)
    _connect_data_sources(client)

    resp = client.get("/api/units/no_such_app/versions")

    assert resp.status_code == 200
    assert resp.get_json() == {"versions": []}


def test_unit_versions_requires_login_and_the_source_repo_connection():
    """It reads the source repository with the caller's own credentials, so
    the config-mgmt DB connection is not the one that grants it."""
    client = _client()

    resp = client.get("/api/units/sensor_app/versions")
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "authentication required"}

    _login(client)
    _connect_config_mgmt_db(client)
    resp = client.get("/api/units/sensor_app/versions")
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "source code repo connection required"}


def test_unit_versions_access_error_maps_to_502():
    components = _components(
        source_repo=FakeSourceCodeRepository(raise_error=SourceRepoAccessError("gitea down"))
    )
    client = _client(components)
    _login(client)
    _connect_data_sources(client)

    resp = client.get("/api/units/sensor_app/versions")

    assert resp.status_code == 502
    assert "gitea down" in resp.get_json()["error"]


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


def test_run_submits_the_signed_in_user_as_the_producer():
    """The username never reached the worker before; it is what lets a
    listing say who produced each file."""
    submitted = {}
    components = _components(
        task_runner=FakeTaskRunner(run=lambda **ids: submitted.update(ids) or {})
    )
    client = _client(components)
    _login(client, username="operator", password="operator")
    _connect_data_sources(client)

    assert client.post("/api/msd/run", json=SELECTION).status_code == 202
    assert submitted["produced_by"] == "operator"


def test_run_forwards_the_candidate_version_under_evaluation():
    """SRS DSM-MSD req 11: the unit and version being evaluated for
    installation reach the run that has to acquire them."""
    submitted = {}
    components = _components(
        task_runner=FakeTaskRunner(run=lambda **ids: submitted.update(ids) or {})
    )
    client = _client(components)
    _login(client)
    _connect_data_sources(client)

    body = dict(SELECTION, candidate={"unit_name": "sensor_app", "version": "1.0.3"})
    assert client.post("/api/msd/run", json=body).status_code == 202

    assert submitted["candidate"] == {"unit_name": "sensor_app", "version": "1.0.3"}


def test_run_without_a_candidate_submits_none():
    """Most runs describe the versions the selected system version defines;
    an absent candidate is not an error."""
    submitted = {}
    components = _components(
        task_runner=FakeTaskRunner(run=lambda **ids: submitted.update(ids) or {})
    )
    client = _client(components)
    _login(client)
    _connect_data_sources(client)

    assert client.post("/api/msd/run", json=SELECTION).status_code == 202

    assert submitted["candidate"] is None


def test_run_refuses_a_malformed_candidate():
    """Refused here rather than dropped in the worker, where a silently
    ignored candidate would produce a run of versions nobody asked for."""
    client = _client()
    _login(client)
    _connect_data_sources(client)

    resp = client.post("/api/msd/run", json=dict(SELECTION, candidate="sensor_app"))
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "candidate must be a JSON object"}

    resp = client.post("/api/msd/run", json=dict(SELECTION, candidate={"unit_name": "sensor_app"}))
    assert resp.status_code == 400
    assert "version" in resp.get_json()["error"]

    resp = client.post("/api/msd/run", json=dict(SELECTION, candidate={"version": "1.0.3"}))
    assert resp.status_code == 400
    assert "unit_name" in resp.get_json()["error"]


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
        source_repo_factory=lambda ds: FakeSourceCodeRepository(),
        msd_task_runner=_BrokenCancelRunner(run=lambda **ids: None),
        auth_repo=LdapAuthRepository(),
        task_output_store=FakeTaskOutputStore(),
    )
    client = _client(components)
    _login(client)

    resp = client.post("/api/msd/tasks/does-not-exist/cancel")

    assert resp.status_code == 502
    assert "broker down" in resp.get_json()["error"]


def _completed_task_id(components: Components, client) -> str:
    _connect_data_sources(client)
    return client.post("/api/msd/run", json=SELECTION).get_json()["task_id"]


def test_task_state_serves_status_and_lines():
    components = _components()
    client = _client(components)
    _login(client)
    task_id = _completed_task_id(components, client)
    components.task_output_store.append(task_id, "clone: nav_app 1.0.0 cloned to /ws")
    components.task_output_store.append(task_id, "generate: wrote model setup data to /ws/model_setup_data.json")

    resp = client.get(f"/api/msd/tasks/{task_id}")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["state"] == "SUCCESS"
    assert body["result"]  # the terminal payload carries the run's result
    assert body["lines"] == [
        "clone: nav_app 1.0.0 cloned to /ws",
        "generate: wrote model setup data to /ws/model_setup_data.json",
    ]


def test_task_state_resumes_after_the_last_line_seen():
    """`after` is the index of the last line the client holds, so the answer
    carries only what is new — nothing it already has is replayed."""
    components = _components()
    client = _client(components)
    _login(client)
    task_id = _completed_task_id(components, client)
    for line in ("line one", "line two", "line three"):
        components.task_output_store.append(task_id, line)

    resp = client.get(f"/api/msd/tasks/{task_id}?after=1")

    body = resp.get_json()
    assert body["lines"] == ["line three"]
    assert body["state"] == "SUCCESS"  # the status rides along with the lines


def test_task_state_reports_progress_while_the_state_holds():
    """While the state sits on STARTED, the payload's progress field is what
    advances — each poll reports the progress the task has published so far,
    so the UI's bar moves without the state label ever changing."""
    components = Components(
        defaults=_DEFAULTS,
        config_repo_factory=lambda ds: FakeConfigManagementRepository(),
        source_repo_factory=lambda ds: FakeSourceCodeRepository(),
        msd_task_runner=FakeTaskRunner(
            run=lambda **ids: {"selection": {k: ids[k] for k in SELECTION}},
            state_sequence=[
                "PENDING",
                TaskStatus("t", "STARTED", info={"percent": 10, "phase": "clone"}),
                TaskStatus("t", "STARTED", info={"percent": 25, "phase": "clone"}),
            ],
        ),
        auth_repo=LdapAuthRepository(),
        task_output_store=FakeTaskOutputStore(),
    )
    client = _client(components)
    _login(client)
    task_id = _completed_task_id(components, client)

    first = client.get(f"/api/msd/tasks/{task_id}").get_json()
    second = client.get(f"/api/msd/tasks/{task_id}").get_json()
    third = client.get(f"/api/msd/tasks/{task_id}").get_json()
    fourth = client.get(f"/api/msd/tasks/{task_id}").get_json()

    assert first["state"] == "PENDING"
    assert first.get("progress") is None
    assert second["state"] == "STARTED"
    assert second["progress"]["percent"] == 10
    assert third["state"] == "STARTED"
    assert third["progress"]["percent"] == 25
    assert fourth["state"] == "SUCCESS"  # and the terminal payload ends it


def test_task_state_bad_cursor_reads_as_hold_nothing():
    """A malformed cursor cannot slice from the end of the log — it reads as
    'hold nothing', so the answer is the whole list rather than its tail."""
    components = _components()
    client = _client(components)
    _login(client)
    task_id = _completed_task_id(components, client)
    components.task_output_store.append(task_id, "line one")
    components.task_output_store.append(task_id, "line two")

    body = client.get(f"/api/msd/tasks/{task_id}?after=not-a-number").get_json()

    assert body["lines"] == ["line one", "line two"]


def test_task_state_requires_login():
    resp = _client().get("/api/msd/tasks/does-not-exist")

    assert resp.status_code == 401
    assert resp.get_json() == {"error": "authentication required"}


def _file_payload(generated_at="2026-09-02T14:15:30", produced_by="operator", scale=None):
    return {
        "context": {},
        "inventory": {"units": []},
        "acquired_files": [],
        "validation_errors": [],
        "generated_at": generated_at,
        "produced_by": produced_by,
        "graph": {"metadata": {"scale": scale or {"apps": 2}}},
    }


def test_msd_files_lists_what_earlier_runs_produced(tmp_path):
    _produce(tmp_path, "task-a", _file_payload("2026-09-01T09:02:00", "admin"))
    _produce(tmp_path, "task-b", _file_payload("2026-09-02T14:15:30", "operator"))
    client = _client(_components(workspace=tmp_path))
    _login(client)
    _connect_config_mgmt_db(client)

    resp = client.get(_files_url())

    assert resp.status_code == 200
    files = resp.get_json()["files"]
    assert [f["run_id"] for f in files] == ["task-b", "task-a"]
    assert files[0] == {
        "run_id": "task-b",
        "project_id": "proj-1",
        "platform_id": "plat-1",
        "version_id": "1.0.0",
        "generated_at": "2026-09-02T14:15:30",
        "produced_by": "operator",
        "scale": {"apps": 2},
        "candidate": None,
    }


def test_msd_files_lists_every_producers_files_not_only_the_callers(tmp_path):
    """SRS DSM-VAE req 5 scopes the listing by selection, not by user."""
    _produce(tmp_path, "task-a", _file_payload(produced_by="operator"))
    client = _client(_components(workspace=tmp_path))
    _login(client, username="admin", password="admin")
    _connect_config_mgmt_db(client)

    files = client.get(_files_url()).get_json()["files"]

    assert [f["produced_by"] for f in files] == ["operator"]


def test_msd_files_is_empty_for_a_selection_that_produced_nothing(tmp_path):
    client = _client(_components(workspace=tmp_path))
    _login(client)
    _connect_config_mgmt_db(client)

    assert client.get(_files_url()).get_json() == {"files": []}


def test_msd_files_requires_login_and_a_config_db_connection(tmp_path):
    resp = _client().get(_files_url())
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "authentication required"}

    client = _client()
    _login(client)
    resp = client.get(_files_url())
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "config management database connection required"}


def test_download_serves_a_produced_file_as_an_attachment(tmp_path):
    _produce(tmp_path, "task-a", {"apps": 2, "generated_at": "2026-09-02T14:15:30"})
    client = _client(_components(workspace=tmp_path))
    _login(client)
    _connect_config_mgmt_db(client)

    resp = client.get(_files_url("task-a", "/download"))

    assert resp.status_code == 200
    assert resp.content_type == "application/json"
    assert "attachment" in resp.headers["Content-Disposition"]
    assert "model_setup_data.json" in resp.headers["Content-Disposition"]
    assert resp.get_json()["apps"] == 2


def test_model_serves_a_produced_file_inline(tmp_path):
    _produce(tmp_path, "task-a", _file_payload())
    client = _client(_components(workspace=tmp_path))
    _login(client)
    _connect_config_mgmt_db(client)

    resp = client.get(_files_url("task-a", "/model"))

    assert resp.status_code == 200
    assert resp.content_type == "application/json"
    # Inline, unlike /download: the card reads this one rather than saving it.
    assert "attachment" not in resp.headers.get("Content-Disposition", "")
    assert resp.get_json()["produced_by"] == "operator"


def test_a_produced_file_outlives_the_runs_execution_record(tmp_path):
    """The regression this addressing scheme exists for: nothing consults the
    task runner, so a file stays reachable after its result has expired."""
    _produce(tmp_path, "task-a", _file_payload())
    components = _components(workspace=tmp_path)
    client = _client(components)
    _login(client)
    _connect_config_mgmt_db(client)

    # The runner has never heard of this task id.
    assert components.msd_task_runner.status("task-a").result is None

    assert client.get(_files_url("task-a", "/model")).status_code == 200
    assert client.get(_files_url("task-a", "/download")).status_code == 200


def test_unknown_run_id_reports_404(tmp_path):
    client = _client(_components(workspace=tmp_path))
    _login(client)
    _connect_config_mgmt_db(client)

    for suffix in ("/model", "/download"):
        resp = client.get(_files_url("does-not-exist", suffix))
        assert resp.status_code == 404
        assert resp.get_json() == {"error": "model setup data file not found"}


def test_a_run_id_escaping_the_workspace_reports_404(tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text('{"generated_at": "2026-09-02T00:00:00"}')
    client = _client(_components(workspace=tmp_path / "ws"))
    _login(client)
    _connect_config_mgmt_db(client)

    resp = client.get(_files_url("..", "/download", selection={
        "project_id": "..", "platform_id": "..", "version_id": ".."
    }))

    assert resp.status_code == 404


def test_file_routes_require_login(tmp_path):
    for suffix in ("/model", "/download"):
        resp = _client().get(_files_url("task-a", suffix))
        assert resp.status_code == 401
        assert resp.get_json() == {"error": "authentication required"}


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
        source_repo_factory=lambda ds: FakeSourceCodeRepository(),
        msd_task_runner=_BrokenRunner(run=lambda **ids: None),
        auth_repo=LdapAuthRepository(),
        task_output_store=FakeTaskOutputStore(),
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


def test_connect_source_repo_requires_login():
    resp = _connect_source_repo(_client())

    assert resp.status_code == 401


def test_connect_source_repo_without_config_mgmt_db():
    """The two sources are peers: either may be connected first."""
    client = _client()
    _login(client)

    resp = _connect_source_repo(client)
    assert resp.status_code == 200

    body = client.get("/api/session").get_json()
    assert body["source_code_repo_connected"] is True
    assert body["config_mgmt_db_connected"] is False


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
        source_repo_factory=lambda ds: FakeSourceCodeRepository(),
        msd_task_runner=FakeTaskRunner(run=lambda **ids: None),
        auth_repo=LdapAuthRepository(),
        task_output_store=FakeTaskOutputStore(),
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


def test_login_sets_persistent_session_cookie():
    """A full browser close must not sever the session: without an expiry the
    browser drops the cookie on close, and the tracked run goes with it (the
    output survives in the store, the session link to it does not)."""
    resp = _login(_client())

    set_cookie = resp.headers["Set-Cookie"]
    assert "Expires=" in set_cookie or "Max-Age=" in set_cookie


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
    assert body["ui"] is None


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
    assert body["source_code_repo_connected"] is True  # the sibling source is left alone


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
    assert active_task["candidate"] is None
    assert active_task["submitted_at"] > 0


def test_session_survives_browser_restart_with_active_run():
    """Closing the browser and reopening it sends the same — now persistent —
    session cookie back: the reopened client must find the session intact —
    sources, selection, and the run it was tracking. Both clients share the
    app's components, since the data-source connections live in memory under
    the session's conn_token, exactly as they do for one real browser."""
    app = create_app(_components())
    client = app.test_client()
    _login(client)
    _connect_data_sources(client)
    client.post("/api/selection", json=SELECTION)
    task_id = client.post("/api/msd/run", json=SELECTION).get_json()["task_id"]

    cookie = client.get_cookie("session").value
    reopened = app.test_client()
    reopened.set_cookie("session", cookie)

    body = reopened.get("/api/session").get_json()
    assert body["authenticated"] is True
    assert body["config_mgmt_db_connected"] is True
    assert body["source_code_repo_connected"] is True
    assert body["selection"] == SELECTION
    assert body["active_task"]["task_id"] == task_id


def test_active_task_remembers_the_candidate_the_run_is_evaluating():
    """The run card describes the run after a reload, and a candidate run is
    not the same run as one of the versions the system version defines."""
    client = _client()
    _login(client)
    _connect_data_sources(client)
    candidate = {"unit_name": "sensor_app", "version": "1.0.3"}

    client.post("/api/msd/run", json=dict(SELECTION, candidate=candidate))

    assert client.get("/api/session").get_json()["active_task"]["candidate"] == candidate


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


UI = {"view": "model", "model_file": "run-1", "candidate": {"unit_name": "sensor_app", "version": "1.0.2"}}


def _set_ui(client, **overrides):
    return client.post("/api/session/ui", json=dict(UI, **overrides))


def test_ui_record_is_reflected_in_session():
    client = _client()
    _login(client)
    _connect_data_sources(client)

    resp = _set_ui(client)
    assert resp.status_code == 204

    assert client.get("/api/session").get_json()["ui"] == UI


def test_ui_record_defaults_the_parts_a_card_does_not_carry():
    client = _client()
    _login(client)

    assert _set_ui(client, view="sources", model_file=None, candidate=None).status_code == 204

    assert client.get("/api/session").get_json()["ui"] == {
        "view": "sources",
        "model_file": None,
        "candidate": None,
    }


def test_ui_record_requires_login():
    resp = _set_ui(_client())

    assert resp.status_code == 401
    assert resp.get_json() == {"error": "authentication required"}


def test_ui_record_refuses_a_card_that_cannot_be_resumed():
    client = _client()
    _login(client)
    _set_ui(client)

    for view in ("boot", "login", "elsewhere", None):
        resp = _set_ui(client, view=view)
        assert resp.status_code == 400, view
        assert "view must be one of" in resp.get_json()["error"]

    # The refused writes left the standing record alone.
    assert client.get("/api/session").get_json()["ui"] == UI


def test_ui_record_refuses_a_malformed_candidate():
    client = _client()
    _login(client)
    _set_ui(client)

    resp = _set_ui(client, candidate={"unit_name": "sensor_app"})
    assert resp.status_code == 400
    assert "candidate missing field" in resp.get_json()["error"]

    assert client.get("/api/session").get_json()["ui"] == UI


def test_selecting_a_different_context_drops_the_ui_record():
    client = _client()
    _login(client)
    _connect_data_sources(client)
    client.post("/api/selection", json=SELECTION)
    _set_ui(client)

    # The same selection again is not a change of context: the file on show
    # and the candidate still describe it.
    assert client.post("/api/selection", json=SELECTION).status_code == 200
    assert client.get("/api/session").get_json()["ui"] == UI

    other = dict(SELECTION, version_id="ver-other")
    assert client.post("/api/selection", json=other).status_code == 200
    assert client.get("/api/session").get_json()["ui"] is None


def test_delete_selection_clears_the_ui_record():
    client = _client()
    _login(client)
    _connect_data_sources(client)
    client.post("/api/selection", json=SELECTION)
    _set_ui(client)

    assert client.delete("/api/selection").status_code == 204

    assert client.get("/api/session").get_json()["ui"] is None


def test_reconnecting_config_mgmt_db_clears_the_ui_record():
    client = _client()
    _login(client)
    _connect_data_sources(client)
    client.post("/api/selection", json=SELECTION)
    _set_ui(client)

    assert _connect_config_mgmt_db(client).status_code == 200

    assert client.get("/api/session").get_json()["ui"] is None


def test_logout_clears_selection_and_active_task():
    client = _client()
    _login(client)
    _connect_data_sources(client)
    client.post("/api/selection", json=SELECTION)
    client.post("/api/msd/run", json=SELECTION)
    _set_ui(client)

    resp = client.post("/api/logout")
    assert resp.status_code == 204

    _login(client)
    body = client.get("/api/session").get_json()
    assert body["selection"] is None
    assert body["active_task"] is None
    assert body["ui"] is None
