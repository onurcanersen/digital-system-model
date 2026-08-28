"""Tests for the combined clone → generate workflow use case (runs directly,
no Celery, no broker)."""

import json
from pathlib import Path

import pytest

from composition import Components
from fakes.fake_config_management_repository import FakeConfigManagementRepository
from fakes.fake_source_code_repository import DiskCloningSourceCodeRepository, FakeSourceCodeRepository
from domain.inventory import SoftwareUnitVersion
from ports.config_management_repository import ConfigManagementAccessError


def _components(tmp_path: Path, source_repo: FakeSourceCodeRepository = None, **config_repo_kwargs) -> Components:
    config_repo = FakeConfigManagementRepository(
        unit_versions={"1.0.0": [SoftwareUnitVersion("nav_app", "1.0.0")]},
        **config_repo_kwargs,
    )
    return Components(
        config_repo=config_repo,
        source_repo=source_repo or DiskCloningSourceCodeRepository(mandatory_files=["Makefile", "src/nav_app.xml"]),
        workspace=tmp_path / "ws",
    )


def _run(components: Components, task_id: str, project_id: str, platform_id: str, version_id: str) -> dict:
    """One workflow run in a task-keyed workspace root, as the Celery task does."""
    return components.workflow().execute(
        components.workspace / task_id, project_id, platform_id, version_id
    ).to_dict()


def test_run_workflow_clones_and_generates(tmp_path: Path):
    components = _components(tmp_path)

    result = _run(components, "task-1", "proj-1", "plat-1", "1.0.0")

    selection_dir = components.workspace / "task-1" / "proj-1" / "plat-1" / "1.0.0"
    assert result["workspace"] == str(selection_dir)
    assert (selection_dir / "nav_app" / "Makefile").is_file()
    assert result["clone"]["units"] == [
        {"unit_name": "nav_app", "version": "1.0.0", "status": "cloned", "detail": str(selection_dir / "nav_app")}
    ]
    assert result["units"] == [{"unit_name": "nav_app", "version": "1.0.0", "status": "ok"}]
    assert result["validation_errors"] == []

    output_path = Path(result["output_path"])
    assert output_path == selection_dir / "model_setup_data.json"
    assert output_path.is_file()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert "context" not in payload and "acquired_files" not in payload
    assert payload["metadata"]["scale"]["topics"] >= 0


def test_run_workflow_records_clone_errors_per_unit(tmp_path: Path):
    components = _components(tmp_path, source_repo=DiskCloningSourceCodeRepository(fail_units={"nav_app"}, mandatory_files=["Makefile", "src/nav_app.xml"]))

    result = _run(components, "task-2", "proj-1", "plat-1", "1.0.0")

    assert result["clone"]["units"][0]["status"] == "error"
    assert "cannot clone" in result["clone"]["units"][0]["detail"]
    assert result["units"][0]["status"] == "not_cloned"
    assert Path(result["output_path"]).is_file()


def test_run_workflow_fails_when_config_db_is_down(tmp_path: Path):
    components = _components(tmp_path, raise_error=ConfigManagementAccessError("db down"))

    with pytest.raises(Exception, match="db down"):
        _run(components, "task-3", "proj-1", "plat-1", "1.0.0")


def test_run_workflow_fails_for_unknown_platform(tmp_path: Path):
    components = _components(tmp_path)

    with pytest.raises(RuntimeError, match="no-such-platform"):
        _run(components, "task-4", "proj-1", "no-such-platform", "1.0.0")


def test_run_workflow_isolates_workspaces_per_task_id(tmp_path: Path):
    components = _components(tmp_path)

    first = _run(components, "task-a", "proj-1", "plat-1", "1.0.0")
    second = _run(components, "task-b", "proj-1", "plat-1", "1.0.0")

    assert Path(first["workspace"]) != Path(second["workspace"])
    assert (Path(first["workspace"]) / "nav_app" / "Makefile").is_file()
    assert (Path(second["workspace"]) / "nav_app" / "Makefile").is_file()
