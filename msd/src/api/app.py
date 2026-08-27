"""Flask server + single-page UI for the MSD workflow.

The three workflow steps:
  1. Selection:  GET /api/projects, /api/platforms, /api/versions, /api/units
  2. Run:        POST /api/run  body {"project_id", "platform_id", "version_id"}
                 enqueues the combined clone → generate step as a Celery
                 task and returns 202 {"task_id", "status_url"}
  3. Status:     GET /api/task/<task_id> → {"task_id", "state", "result"|"error"}
                 (the task clones into <workspace>/<task_id>/<project>/
                 <platform>/<version> and writes model_setup_data.json there)

Workflow mapping (SRS DSM-MSD): selection = req 5, cloning = req 13,
parsing/generation = req 19.

Run with:  python src/api/app.py
Env vars:  MSD_API_HOST (default 127.0.0.1), MSD_API_PORT (default 8080),
            MSD_WORKSPACE (default <msd>/workspace)
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

from flask import Flask, jsonify, render_template, request

# Allow `python src/api/app.py` from anywhere: make src/ importable.
_SRC_DIR = Path(__file__).resolve().parents[1]
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from api.composition import Components  # noqa: E402
from ports.config_management_repository import ConfigManagementAccessError  # noqa: E402
from ports.task_runner import ITaskRunner  # noqa: E402

logger = logging.getLogger(__name__)

_SELECTION_FIELDS = ("project_id", "platform_id", "version_id")


def _selection_from_query() -> Tuple[Optional[Dict[str, str]], Optional[Tuple[str, int]]]:
    ids = {}
    missing = []
    for key in _SELECTION_FIELDS:
        value = request.args.get(key)
        if value:
            ids[key] = value
        else:
            missing.append(key)
    if missing:
        return None, (f"missing query parameter(s): {', '.join(missing)}", 400)
    return ids, None


def _selection_from_body() -> Tuple[Optional[Dict[str, str]], Optional[Tuple[str, int]]]:
    body = request.get_json(silent=True, force=True)
    if not isinstance(body, dict):
        return None, ("request body must be a JSON object", 400)
    ids = {}
    missing = []
    for key in _SELECTION_FIELDS:
        value = body.get(key)
        if value:
            ids[key] = str(value)
        else:
            missing.append(key)
    if missing:
        return None, (f"missing required field(s): {', '.join(missing)}", 400)
    return ids, None


def create_app(components: Components, task_runner: Optional[ITaskRunner] = None) -> Flask:
    if task_runner is None:
        # Lazy import: the Celery stack is only needed for the default runner,
        # and must not be a hard dependency for apps/tests that inject one.
        from adapters.celery_task_runner import CeleryTaskRunner
        task_runner = CeleryTaskRunner()

    app = Flask(__name__)

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/projects")
    def api_projects():
        try:
            projects = components.config_repo.list_projects()
        except ConfigManagementAccessError as exc:
            return jsonify({"error": str(exc)}), 502
        return jsonify({"projects": [p.to_dict() for p in projects]})

    @app.route("/api/platforms")
    def api_platforms():
        project_id = request.args.get("project_id")
        if not project_id:
            return jsonify({"error": "missing query parameter: project_id"}), 400
        try:
            platforms = components.config_repo.list_platforms(project_id)
        except ConfigManagementAccessError as exc:
            return jsonify({"error": str(exc)}), 502
        return jsonify({"platforms": [p.to_dict() for p in platforms]})

    @app.route("/api/versions")
    def api_versions():
        project_id = request.args.get("project_id")
        platform_id = request.args.get("platform_id")
        if not project_id or not platform_id:
            return jsonify({"error": "missing query parameter(s): project_id, platform_id"}), 400
        try:
            versions = components.config_repo.list_versions(project_id, platform_id)
        except ConfigManagementAccessError as exc:
            return jsonify({"error": str(exc)}), 502
        return jsonify({"versions": [v.to_dict() for v in versions]})

    @app.route("/api/units")
    def api_units():
        ids, err = _selection_from_query()
        if err:
            return jsonify({"error": err[0]}), err[1]
        try:
            units = components.config_repo.list_unit_versions(
                ids["project_id"], ids["platform_id"], ids["version_id"]
            )
        except ConfigManagementAccessError as exc:
            return jsonify({"error": str(exc)}), 502
        return jsonify({"units": [u.to_dict() for u in units]})

    @app.route("/api/run", methods=["POST"])
    def api_run():
        ids, err = _selection_from_body()
        if err:
            return jsonify({"error": err[0]}), err[1]
        try:
            task_id = task_runner.submit_run(ids["project_id"], ids["platform_id"], ids["version_id"])
        except Exception as exc:
            # The execution backend (broker) is unreachable or rejected the
            # submission — an upstream problem, not a client error.
            logger.warning("run: task submission failed: %s", exc)
            return jsonify({"error": str(exc)}), 502
        return jsonify({"task_id": task_id, "status_url": f"/api/task/{task_id}"}), 202

    @app.route("/api/task/<task_id>")
    def api_task_status(task_id):
        status = task_runner.status(task_id)
        payload = {"task_id": status.task_id, "state": status.state}
        if status.result is not None:
            payload["result"] = status.result
        if status.error is not None:
            payload["error"] = status.error
        return jsonify(payload)

    return app


def main() -> None:
    from api.composition import load_components

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    host = os.environ.get("MSD_API_HOST", "127.0.0.1")
    port = int(os.environ.get("MSD_API_PORT", "8080"))
    app = create_app(load_components())
    print(f"MSD API on http://{host}:{port}", flush=True)
    app.run(host=host, port=port)


if __name__ == "__main__":
    main()
