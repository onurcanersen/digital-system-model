"""Tests for the combined clone → generate workflow function (runs directly,
no Celery, no broker)."""

import json
from pathlib import Path

import pytest

from api.composition import Components
from fakes.fake_config_management_repository import FakeConfigManagementRepository
from fakes.fake_source_code_repository import FakeSourceCodeRepository
from model.inventory import SoftwareUnitVersion
from ports.config_management_repository import ConfigManagementAccessError
from ports.source_code_repository import SourceRepoAccessError
from tasks.workflow import run_workflow


class _DiskCloningRepository(FakeSourceCodeRepository):
    """Clone that actually writes the unit directory to disk, like the git adapter."""

    def __init__(self, fail_units=()):
        super().__init__(mandatory_files=["Makefile", "src/nav_app.xml"])
        self._fail_units = set(fail_units)

    def clone_unit(self, unit, dest_dir):
        if unit.unit_name in self._fail_units:
            raise SourceRepoAccessError(f"cannot clone '{unit.unit_name}'")
        unit_dir = dest_dir / unit.unit_name
        (unit_dir / "src").mkdir(parents=True, exist_ok=True)
        (unit_dir / "Makefile").write_text("all:\n", encoding="utf-8")
        (unit_dir / "src" / f"{unit.unit_name}.xml").write_text("<manifest/>", encoding="utf-8")
        return super().clone_unit(unit, dest_dir)


def _components(tmp_path: Path, source_repo: FakeSourceCodeRepository = None, **config_repo_kwargs) -> Components:
    config_repo = FakeConfigManagementRepository(
        unit_versions={"1.0.0": [SoftwareUnitVersion("nav_app", "1.0.0")]},
        **config_repo_kwargs,
    )
    return Components(
        config_repo=config_repo,
        source_repo=source_repo or _DiskCloningRepository(),
        workspace=tmp_path / "ws",
    )


def test_run_workflow_clones_and_generates(tmp_path: Path):
    components = _components(tmp_path)

    result = run_workflow(components, "task-1", "proj-1", "plat-1", "1.0.0")

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
    components = _components(tmp_path, source_repo=_DiskCloningRepository(fail_units={"nav_app"}))

    result = run_workflow(components, "task-2", "proj-1", "plat-1", "1.0.0")

    assert result["clone"]["units"][0]["status"] == "error"
    assert "cannot clone" in result["clone"]["units"][0]["detail"]
    assert result["units"][0]["status"] == "not_cloned"
    assert Path(result["output_path"]).is_file()


def test_run_workflow_fails_when_config_db_is_down(tmp_path: Path):
    components = _components(tmp_path, raise_error=ConfigManagementAccessError("db down"))

    with pytest.raises(Exception, match="db down"):
        run_workflow(components, "task-3", "proj-1", "plat-1", "1.0.0")


def test_run_workflow_fails_for_unknown_platform(tmp_path: Path):
    components = _components(tmp_path)

    with pytest.raises(RuntimeError, match="no-such-platform"):
        run_workflow(components, "task-4", "proj-1", "no-such-platform", "1.0.0")


def test_run_workflow_isolates_workspaces_per_task_id(tmp_path: Path):
    components = _components(tmp_path)

    first = run_workflow(components, "task-a", "proj-1", "plat-1", "1.0.0")
    second = run_workflow(components, "task-b", "proj-1", "plat-1", "1.0.0")

    assert Path(first["workspace"]) != Path(second["workspace"])
    assert (Path(first["workspace"]) / "nav_app" / "Makefile").is_file()
    assert (Path(second["workspace"]) / "nav_app" / "Makefile").is_file()
