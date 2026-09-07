"""Tests for the filesystem catalog of produced Model Setup Data files
(SRS DSM-VAE req 5): the workspace layout is the index, and each file's own
header is the listing entry."""

import json
from pathlib import Path

from msd.adapters.filesystem_model_setup_data_catalog import FilesystemModelSetupDataCatalog

SELECTION = ("proj-1", "plat-1", "1.0.0")


def _write_run(workspace: Path, selection, run_id: str, generated_at: str, produced_by=None, scale=None, units=None):
    """One produced file, as RunWorkflow would have left it."""
    run_dir = workspace.joinpath(*selection, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "context": {},
        "inventory": {"units": units if units is not None else []},
        "acquired_files": [],
        "validation_errors": [],
        "generated_at": generated_at,
        "produced_by": produced_by,
        "graph": {"metadata": {"scale": scale or {"apps": 2, "topics": 3}}},
    }
    (run_dir / "model_setup_data.json").write_text(json.dumps(payload), encoding="utf-8")
    return run_dir


def test_lists_the_files_produced_for_a_selection_newest_first(tmp_path: Path):
    _write_run(tmp_path, SELECTION, "task-a", "2026-09-01T09:02:00", produced_by="admin")
    _write_run(tmp_path, SELECTION, "task-b", "2026-09-02T14:15:30", produced_by="operator")
    catalog = FilesystemModelSetupDataCatalog(tmp_path)

    records = catalog.list(*SELECTION)

    assert [r.run_id for r in records] == ["task-b", "task-a"]
    assert [r.produced_by for r in records] == ["operator", "admin"]
    assert records[0].to_dict() == {
        "run_id": "task-b",
        "project_id": "proj-1",
        "platform_id": "plat-1",
        "version_id": "1.0.0",
        "generated_at": "2026-09-02T14:15:30",
        "produced_by": "operator",
        "scale": {"apps": 2, "topics": 3},
        "candidate": None,
    }


def test_a_run_that_evaluated_a_candidate_says_so_in_its_listing_entry(tmp_path: Path):
    """SRS DSM-MSD req 11: several runs of one selection can differ only by the
    candidate they carried, so the listing must be able to tell them apart —
    read back out of the inventory the file itself recorded."""
    baseline_units = [
        {"unit_name": "nav_app", "version": "1.0.0", "is_candidate": False},
        {"unit_name": "sensor_app", "version": "1.0.0", "is_candidate": False},
    ]
    candidate_units = [
        {"unit_name": "nav_app", "version": "1.0.0", "is_candidate": False},
        {"unit_name": "sensor_app", "version": "1.0.3", "is_candidate": True},
    ]
    _write_run(tmp_path, SELECTION, "task-a", "2026-09-01T09:02:00", units=baseline_units)
    _write_run(tmp_path, SELECTION, "task-b", "2026-09-02T14:15:30", units=candidate_units)
    catalog = FilesystemModelSetupDataCatalog(tmp_path)

    by_run = {r.run_id: r for r in catalog.list(*SELECTION)}

    assert by_run["task-b"].candidate == {"unit_name": "sensor_app", "version": "1.0.3"}
    assert by_run["task-a"].candidate is None


def test_a_file_with_an_unexpected_inventory_shape_still_lists(tmp_path: Path):
    """Reading the candidate must not become a new way for a file to drop out
    of the listing."""
    _write_run(tmp_path, SELECTION, "task-a", "2026-09-01T09:02:00", units="not-a-list")
    _write_run(tmp_path, SELECTION, "task-b", "2026-09-02T14:15:30", units=["not-a-dict"])
    catalog = FilesystemModelSetupDataCatalog(tmp_path)

    records = catalog.list(*SELECTION)

    assert [r.run_id for r in records] == ["task-b", "task-a"]
    assert all(r.candidate is None for r in records)


def test_lists_only_the_files_of_the_requested_selection(tmp_path: Path):
    _write_run(tmp_path, SELECTION, "task-a", "2026-09-01T09:02:00")
    _write_run(tmp_path, ("proj-1", "plat-1", "0.9.0"), "task-b", "2026-09-01T09:03:00")
    _write_run(tmp_path, ("proj-2", "plat-1", "1.0.0"), "task-c", "2026-09-01T09:04:00")
    catalog = FilesystemModelSetupDataCatalog(tmp_path)

    assert [r.run_id for r in catalog.list(*SELECTION)] == ["task-a"]


def test_a_selection_that_produced_nothing_lists_empty(tmp_path: Path):
    catalog = FilesystemModelSetupDataCatalog(tmp_path)

    assert catalog.list(*SELECTION) == []
    assert catalog.list("no-such-project", "plat-1", "1.0.0") == []


def test_unreadable_and_pre_envelope_files_are_skipped_not_fatal(tmp_path: Path):
    """The workspace can hold artifacts from older runs; one bad file must not
    cost the user the rest of their listing."""
    _write_run(tmp_path, SELECTION, "task-ok", "2026-09-02T14:15:30")

    broken = tmp_path.joinpath(*SELECTION, "task-broken")
    broken.mkdir(parents=True)
    (broken / "model_setup_data.json").write_text("{not json", encoding="utf-8")

    # A graph-only file, the shape runs wrote before the full envelope.
    legacy = tmp_path.joinpath(*SELECTION, "task-legacy")
    legacy.mkdir(parents=True)
    (legacy / "model_setup_data.json").write_text(
        json.dumps({"metadata": {}, "nodes": [], "topics": []}), encoding="utf-8"
    )

    # A run dir that holds clones but no output file at all (a failed run).
    tmp_path.joinpath(*SELECTION, "task-empty").mkdir(parents=True)

    catalog = FilesystemModelSetupDataCatalog(tmp_path)

    assert [r.run_id for r in catalog.list(*SELECTION)] == ["task-ok"]


def test_a_file_with_no_timestamp_still_lists_but_sorts_last(tmp_path: Path):
    _write_run(tmp_path, SELECTION, "task-dated", "2026-09-02T14:15:30")
    _write_run(tmp_path, SELECTION, "task-undated", None)
    catalog = FilesystemModelSetupDataCatalog(tmp_path)

    assert [r.run_id for r in catalog.list(*SELECTION)] == ["task-dated", "task-undated"]


def test_resolve_returns_the_path_of_one_produced_file(tmp_path: Path):
    run_dir = _write_run(tmp_path, SELECTION, "task-a", "2026-09-02T14:15:30")
    catalog = FilesystemModelSetupDataCatalog(tmp_path)

    assert catalog.resolve(*SELECTION, "task-a") == run_dir / "model_setup_data.json"


def test_resolve_returns_none_for_an_unknown_run(tmp_path: Path):
    _write_run(tmp_path, SELECTION, "task-a", "2026-09-02T14:15:30")
    catalog = FilesystemModelSetupDataCatalog(tmp_path)

    assert catalog.resolve(*SELECTION, "task-missing") is None


def test_resolve_refuses_components_that_escape_the_workspace(tmp_path: Path):
    """The sanitizer replaces '/' but keeps '.', so a single component can
    climb exactly one level. Four of them — every path part reaches this
    adapter from a URL segment — climb out of the workspace, and containment
    is the only thing that stops it."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = tmp_path / "model_setup_data.json"
    target.write_text('{"generated_at": "2026-09-02T00:00:00"}', encoding="utf-8")

    catalog = FilesystemModelSetupDataCatalog(workspace)

    # ws/../../.. and up — lands outside the workspace, and would otherwise
    # have served a real file sitting there.
    assert catalog.resolve("..", "..", "..", "..") is None
    assert catalog.resolve("..", "..", "..", "ws") is None


def test_resolve_rejects_a_run_id_that_is_not_a_run(tmp_path: Path):
    """A '..' run id stays inside the workspace, so containment does not fire;
    it lands on a directory that holds no Model Setup Data file, and there is
    nothing to serve."""
    _write_run(tmp_path, SELECTION, "task-a", "2026-09-02T14:15:30")
    catalog = FilesystemModelSetupDataCatalog(tmp_path)

    assert catalog.resolve(*SELECTION, "..") is None
    assert catalog.resolve(*SELECTION, ".") is None
