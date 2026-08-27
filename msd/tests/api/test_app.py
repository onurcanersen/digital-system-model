"""Tests for the Flask API: selection is synchronous, the clone → generate
workflow is an asynchronous task with a status endpoint (SRS DSM-MSD req 5, 13, 19).
The task executes in-process via FakeTaskRunner, so no broker is needed."""

import json
from pathlib import Path

from api.app import create_app
from composition import Components
from fakes.fake_config_management_repository import FakeConfigManagementRepository
from fakes.fake_source_code_repository import DiskCloningSourceCodeRepository
from fakes.fake_task_runner import FakeTaskRunner
from model.inventory import SoftwareUnitVersion
from ports.config_management_repository import ConfigManagementAccessError


def _components(tmp_path: Path, **config_repo_kwargs) -> Components:
    config_repo = FakeConfigManagementRepository(
        unit_versions={"1.0.0": [SoftwareUnitVersion("nav_app", "1.0.0")]},
        **config_repo_kwargs,
    )
    return Components(
        config_repo=config_repo,
        source_repo=DiskCloningSourceCodeRepository(mandatory_files=["Makefile", "src/nav_app.xml"]),
        workspace=tmp_path / "ws",
    )


def _runner(components: Components) -> FakeTaskRunner:
    """In-process runner: executes the real workflow synchronously per submit."""
    return FakeTaskRunner(
        run=lambda task_id, **ids: components.workflow_uc().execute(
            components.workspace / task_id, **ids
        ).to_dict()
    )


def _client(components: Components, task_runner: FakeTaskRunner = None):
    """Flask test client over the app built from the given components."""
    return create_app(components, task_runner=task_runner or _runner(components)).test_client()


SELECTION = {"project_id": "proj-1", "platform_id": "plat-1", "version_id": "1.0.0"}


def test_index_serves_the_ui(tmp_path: Path):
    client = _client(_components(tmp_path))

    resp = client.get("/")

    assert resp.status_code == 200
    assert "Model Setup Data" in resp.text
    assert "/api/run" in resp.text
    assert "/api/task/" in resp.text


def test_selection_endpoints(tmp_path: Path):
    client = _client(_components(tmp_path))

    resp = client.get("/api/projects")
    assert resp.status_code == 200
    assert resp.get_json()["projects"][0]["project_id"] == "proj-1"

    resp = client.get("/api/projects/proj-1/platforms")
    assert resp.status_code == 200
    assert resp.get_json()["platforms"][0]["platform_id"] == "plat-1"

    resp = client.get("/api/projects/proj-1/platforms/plat-1/versions")
    assert resp.status_code == 200
    assert resp.get_json()["versions"][0]["is_effective"] is True

    resp = client.get("/api/projects/proj-1/platforms/plat-1/versions/1.0.0/units")
    assert resp.status_code == 200
    assert resp.get_json()["units"][0]["unit_name"] == "nav_app"


def test_run_is_async_and_writes_per_task_workspace(tmp_path: Path):
    components = _components(tmp_path)
    client = _client(components)

    resp = client.post("/api/run", json=SELECTION)
    assert resp.status_code == 202
    body = resp.get_json()
    task_id = body["task_id"]
    assert task_id
    assert body["status_url"] == f"/api/task/{task_id}"

    status = client.get(f"/api/task/{task_id}").get_json()
    assert status["state"] == "SUCCESS"
    result = status["result"]
    selection_dir = Path(result["workspace"])
    assert selection_dir == components.workspace / task_id / "proj-1" / "plat-1" / "1.0.0"
    assert (selection_dir / "nav_app" / "Makefile").is_file()
    assert result["clone"]["units"][0]["status"] == "cloned"
    assert result["units"][0]["status"] == "ok"
    assert result["validation_errors"] == []

    output_path = Path(result["output_path"])
    assert output_path == selection_dir / "model_setup_data.json"
    assert output_path.is_file()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert "context" not in payload and "acquired_files" not in payload
    assert payload["metadata"]["scale"]["topics"] >= 0


def test_runs_are_isolated_per_task_id_and_never_reuse(tmp_path: Path):
    components = _components(tmp_path)
    client = _client(components)

    first = client.post("/api/run", json=SELECTION).get_json()
    second = client.post("/api/run", json=SELECTION).get_json()
    assert second["task_id"] != first["task_id"]

    first_dir = Path(client.get(f"/api/task/{first['task_id']}").get_json()["result"]["workspace"])
    second_dir = Path(client.get(f"/api/task/{second['task_id']}").get_json()["result"]["workspace"])
    assert first_dir != second_dir

    # A new run clones again instead of reusing the previous run's checkout.
    second_result = client.get(f"/api/task/{second['task_id']}").get_json()["result"]
    assert second_result["clone"]["units"][0]["status"] == "cloned"
    assert (second_dir / "nav_app" / "Makefile").is_file()


def test_run_records_per_unit_clone_errors(tmp_path: Path):
    components = _components(tmp_path)
    components.source_repo = DiskCloningSourceCodeRepository(fail_units={"nav_app"}, mandatory_files=["Makefile", "src/nav_app.xml"])
    client = _client(components)

    task_id = client.post("/api/run", json=SELECTION).get_json()["task_id"]
    status = client.get(f"/api/task/{task_id}").get_json()

    assert status["state"] == "SUCCESS"
    result = status["result"]
    assert result["clone"]["units"][0]["status"] == "error"
    assert "cannot clone" in result["clone"]["units"][0]["detail"]
    assert result["units"][0]["status"] == "not_cloned"
    assert Path(result["output_path"]).is_file()


def test_config_db_failure(tmp_path: Path):
    components = _components(tmp_path)
    components.config_repo = FakeConfigManagementRepository(raise_error=ConfigManagementAccessError("db down"))
    client = _client(components)

    resp = client.get("/api/projects")
    assert resp.status_code == 502
    assert "db down" in resp.get_json()["error"]

    task_id = client.post("/api/run", json=SELECTION).get_json()["task_id"]
    status = client.get(f"/api/task/{task_id}").get_json()
    assert status["state"] == "FAILURE"
    assert "db down" in status["error"]


def test_unknown_task_id_reports_pending(tmp_path: Path):
    client = _client(_components(tmp_path))

    resp = client.get("/api/task/does-not-exist")

    assert resp.status_code == 200
    assert resp.get_json() == {"task_id": "does-not-exist", "state": "PENDING"}


def test_selection_body_validation(tmp_path: Path):
    client = _client(_components(tmp_path))

    resp = client.post("/api/run", json={})
    assert resp.status_code == 400
    assert "missing field" in resp.get_json()["error"]

    resp = client.post("/api/run", data=b"not json", content_type="application/json")
    assert resp.status_code == 400


def test_runner_submission_failure_maps_to_502(tmp_path: Path):
    class _BrokenRunner(FakeTaskRunner):
        def submit_run(self, project_id, platform_id, version_id):
            raise RuntimeError("broker down")

    client = create_app(_components(tmp_path), task_runner=_BrokenRunner(run=lambda **ids: None)).test_client()

    resp = client.post("/api/run", json=SELECTION)
    assert resp.status_code == 502
    assert "broker down" in resp.get_json()["error"]
