"""MSD workflow application: the Flask API (SRS DSM-MSD req 4, 5, 13, 19).
The Celery worker lives in worker.py; the shared composition root
(Components, load_components) lives in composition.py.

Flask endpoints:
  GET  /
  GET  /api/projects
  GET  /api/projects/<project_id>/platforms
  GET  /api/projects/<project_id>/platforms/<platform_id>/versions
  GET  /api/projects/<project_id>/platforms/<platform_id>/versions/<version_id>/units
  POST /api/run  body {"project_id", "platform_id", "version_id"}
  GET  /api/tasks/<task_id>

Run the API with:  python api.py  (from the msd/ directory)
Run the Celery worker (same venv, same config.ini) with:
  python worker.py

The API host/port come from the [api] section of config.ini; POST /api/run
submits the msd.run_msd_workflow Celery task (worker.py) through
CeleryTaskRunner, and GET /api/tasks/<task_id> reads its state from the
Celery result backend.

`create_app()` takes a `Components` composition (composition.py, built by
`load_components()` from config.ini) and an `ITaskRunner`; both the API
and the Celery worker use the same composition root.
"""

from __future__ import annotations

import logging

from flask import Flask, jsonify, render_template, request

from composition import Components, load_components
from config import get_config
from ports.config_management_repository import ConfigManagementAccessError
from ports.task_runner import ITaskRunner

logger = logging.getLogger(__name__)

_SELECTION = ("project_id", "platform_id", "version_id")


def create_app(components: Components = None, task_runner: ITaskRunner = None) -> Flask:
    app = Flask(__name__)

    if components is None:
        components = load_components()
    if task_runner is None:
        from adapters.celery_task_runner import CeleryTaskRunner
        task_runner = CeleryTaskRunner()

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

    @app.route("/api/projects/<project_id>/platforms")
    def api_platforms(project_id):
        try:
            platforms = components.config_repo.list_platforms(project_id)
        except ConfigManagementAccessError as exc:
            return jsonify({"error": str(exc)}), 502
        return jsonify({"platforms": [p.to_dict() for p in platforms]})

    @app.route("/api/projects/<project_id>/platforms/<platform_id>/versions")
    def api_versions(project_id, platform_id):
        try:
            versions = components.config_repo.list_versions(project_id, platform_id)
        except ConfigManagementAccessError as exc:
            return jsonify({"error": str(exc)}), 502
        return jsonify({"versions": [v.to_dict() for v in versions]})

    @app.route("/api/projects/<project_id>/platforms/<platform_id>/versions/<version_id>/units")
    def api_units(project_id, platform_id, version_id):
        try:
            units = components.config_repo.list_unit_versions(project_id, platform_id, version_id)
        except ConfigManagementAccessError as exc:
            return jsonify({"error": str(exc)}), 502
        return jsonify({"units": [u.to_dict() for u in units]})

    @app.route("/api/run", methods=["POST"])
    def api_run():
        body = request.get_json(silent=True, force=True)
        if not isinstance(body, dict):
            return jsonify({"error": "request body must be a JSON object"}), 400
        missing = [key for key in _SELECTION if not body.get(key)]
        if missing:
            return jsonify({"error": f"missing field(s): {', '.join(missing)}"}), 400
        try:
            task_id = task_runner.submit_run(body["project_id"], body["platform_id"], body["version_id"])
        except Exception as exc:
            logger.warning("run: task submission failed: %s", exc)
            return jsonify({"error": str(exc)}), 502
        return jsonify({"task_id": task_id, "status_url": f"/api/tasks/{task_id}"}), 202

    @app.route("/api/tasks/<task_id>")
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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = create_app(load_components())
    api = get_config().api
    print(f"MSD API on http://{api.host}:{api.port}", flush=True)
    app.run(host=api.host, port=api.port)


if __name__ == "__main__":
    main()
