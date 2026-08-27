"""The combined clone → generate workflow as a single Celery task.

One task = one isolated run: all artifacts (cloned unit repositories and
model_setup_data.json) live under <workspace>/<task_id>/<project>/<platform>/
<version>, so concurrent runs never collide and runs never reuse previous
artifacts. Per-unit failures are recorded in the result payload; context-level
failures (config DB unreachable, platform not found) raise and fail the task.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List

from api.composition import Components, load_components
from model.status import AcquisitionStatus
from tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

MSD_JSON_FILE_NAME = "model_setup_data.json"

STATUS_NOT_CLONED = "not_cloned"
STATUS_MISSING_FILES = "missing_files"
STATUS_ERROR = "error"
STATUS_OK = "ok"


def parse_unit_summary(data, selection_dir: Path) -> List[dict]:
    """Per-unit parse-stage status: ok / missing_files / error / not_cloned,
    derived from the acquired-file records and the on-disk unit directories."""
    statuses_by_unit: Dict[str, set] = {}
    for record in data.acquired_files:
        statuses_by_unit.setdefault(record.unit_name, set()).add(record.status)
    summary = []
    for unit in data.inventory.units:
        statuses = statuses_by_unit.get(unit.unit_name, set())
        if not (selection_dir / unit.unit_name).is_dir():
            status = STATUS_NOT_CLONED
        elif AcquisitionStatus.MISSING_DATA in statuses:
            status = STATUS_MISSING_FILES
        elif AcquisitionStatus.ERROR in statuses:
            status = STATUS_ERROR
        else:
            status = STATUS_OK
        summary.append({"unit_name": unit.unit_name, "version": unit.version, "status": status})
    return summary


def run_workflow(
    components: Components,
    task_id: str,
    project_id: str,
    platform_id: str,
    version_id: str,
) -> dict:
    """Runs cloning, then parsing/MSD-JSON generation, for one selection inside
    the task-private selection dir. Returns the JSON-serializable result dict;
    raises on context-level failures (config DB, missing platform)."""
    selection_dir = components.selection_dir_under(
        components.workspace / task_id, project_id, platform_id, version_id
    )
    output_path = selection_dir / MSD_JSON_FILE_NAME
    logger.info("workflow %s: clone+generate for %s/%s/%s into %s",
                task_id, project_id, platform_id, version_id, selection_dir)

    platforms = components.config_repo.list_platforms(project_id)
    platform = next((p for p in platforms if p.platform_id == platform_id), None)
    if platform is None:
        raise RuntimeError(f"platform '{platform_id}' not found for project '{project_id}'")

    clone_results = components.clone_uc().execute(
        selection_dir,
        project_id=project_id,
        platform_id=platform_id,
        version_id=version_id,
    )

    data = components.parse_uc(platform.name, project_id, version_id, selection_dir).execute(
        selection_dir,
        output_path,
        project_id=project_id,
        platform_id=platform_id,
        version_id=version_id,
    )

    return {
        "workspace": str(selection_dir),
        "output_path": str(output_path),
        "clone": {"units": [r.to_dict() for r in clone_results]},
        "units": parse_unit_summary(data, selection_dir),
        "validation_errors": [e.to_dict() for e in data.validation_errors],
        "scale": data.graph.get("metadata", {}).get("scale", {}),
    }


@celery_app.task(bind=True, name="msd.run_msd_workflow")
def run_msd_workflow(self, project_id: str, platform_id: str, version_id: str) -> dict:
    """Celery entry point: full MSD workflow for one selection, in a workspace
    dir keyed by this task's id."""
    components = load_components()
    return run_workflow(components, self.request.id, project_id, platform_id, version_id)
