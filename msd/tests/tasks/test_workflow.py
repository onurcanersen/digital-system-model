"""Tests for the combined clone → generate workflow use case (runs directly,
no Celery, no broker)."""

import json
from pathlib import Path

import pytest

from msd.composition import Components
from fakes.fake_config_management_repository import FakeConfigManagementRepository
from fakes.fake_source_code_repository import DiskCloningSourceCodeRepository, FakeSourceCodeRepository
from msd.domain.inventory import CandidateUnitVersion, SoftwareUnitVersion
from msd.ports.config_management_repository import ConfigManagementAccessError


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


def _run(
    components: Components,
    task_id: str,
    project_id: str,
    platform_id: str,
    version_id: str,
    produced_by: str = None,
    candidate: CandidateUnitVersion = None,
) -> dict:
    """One workflow run keyed by a task id, as the Celery task does."""
    return components.workflow().execute(
        components.workspace,
        project_id,
        platform_id,
        version_id,
        run_id=task_id,
        produced_by=produced_by,
        candidate=candidate,
    ).to_dict()


def test_run_workflow_clones_and_generates(tmp_path: Path):
    components = _components(tmp_path)

    result = _run(components, "task-1", "proj-1", "plat-1", "1.0.0", produced_by="operator")

    # The run id is the innermost segment, so every run for this selection is a
    # sibling under proj-1/plat-1/1.0.0 and the set of them is one directory read.
    run_dir = components.workspace / "proj-1" / "plat-1" / "1.0.0" / "task-1"
    assert result["run_id"] == "task-1"
    assert result["run_dir"] == str(run_dir)
    assert (run_dir / "nav_app" / "Makefile").is_file()
    assert result["clone"]["units"] == [
        {"unit_name": "nav_app", "version": "1.0.0", "status": "cloned", "detail": str(run_dir / "nav_app")}
    ]
    assert result["units"] == [{"unit_name": "nav_app", "version": "1.0.0", "status": "ok"}]
    assert result["validation_errors"] == []

    output_path = Path(result["output_path"])
    assert output_path == run_dir / "model_setup_data.json"
    assert output_path.is_file()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    # The saved file is the whole Model Setup Data, so a run is traceable from
    # the file alone — long after the task result has expired.
    assert payload["context"]["version"]["label"] == "1.0.0"
    assert [u["unit_name"] for u in payload["inventory"]["units"]] == ["nav_app"]
    assert [f["unit_name"] for f in payload["acquired_files"]] == ["nav_app", "nav_app"]
    assert payload["validation_errors"] == []
    assert payload["generated_at"]
    assert payload["produced_by"] == "operator"
    assert payload["graph"]["metadata"]["scale"]["topics"] >= 0
    assert result["candidate"] is None


def test_run_workflow_acquires_and_records_the_candidate_version(tmp_path: Path):
    """Req 11 end to end: both steps of the run must agree on the candidate —
    the clone fetches that version and the produced file records it — or the
    file would describe versions the run never acquired."""
    source_repo = DiskCloningSourceCodeRepository(mandatory_files=["Makefile", "src/nav_app.xml"])
    components = _components(tmp_path, source_repo=source_repo)

    result = _run(
        components, "task-c", "proj-1", "plat-1", "1.0.0",
        candidate=CandidateUnitVersion("nav_app", "1.0.3"),
    )

    assert result["candidate"] == {"unit_name": "nav_app", "version": "1.0.3"}
    assert source_repo.cloned == [("nav_app", "1.0.3")]
    assert result["clone"]["units"][0]["version"] == "1.0.3"
    assert result["units"] == [{"unit_name": "nav_app", "version": "1.0.3", "status": "ok"}]

    payload = json.loads(Path(result["output_path"]).read_text(encoding="utf-8"))
    assert payload["inventory"]["units"] == [
        {"unit_name": "nav_app", "version": "1.0.3", "is_candidate": True}
    ]


def test_run_workflow_records_no_producer_when_none_is_given(tmp_path: Path):
    components = _components(tmp_path)

    result = _run(components, "task-1", "proj-1", "plat-1", "1.0.0")

    payload = json.loads(Path(result["output_path"]).read_text(encoding="utf-8"))
    assert payload["produced_by"] is None


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


def test_run_workflow_isolates_run_dirs_per_task_id(tmp_path: Path):
    """Two runs of the *same* selection share its directory but never its
    contents: the run id is what keeps their artifacts apart."""
    components = _components(tmp_path)

    first = _run(components, "task-a", "proj-1", "plat-1", "1.0.0")
    second = _run(components, "task-b", "proj-1", "plat-1", "1.0.0")

    first_dir, second_dir = Path(first["run_dir"]), Path(second["run_dir"])
    assert first_dir != second_dir
    assert first_dir.parent == second_dir.parent
    assert (first_dir / "nav_app" / "Makefile").is_file()
    assert (second_dir / "nav_app" / "Makefile").is_file()
