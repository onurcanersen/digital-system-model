"""Flask server for the MSD workflow.

Endpoints:
  GET  /
  GET  /api/projects
  GET  /api/projects/<project_id>/platforms
  GET  /api/projects/<project_id>/platforms/<platform_id>/versions
  GET  /api/projects/<project_id>/platforms/<platform_id>/versions/<version_id>/units
  POST /api/run  body {"project_id", "platform_id", "version_id"}
  GET  /api/task/<task_id>

Run with:  python src/api/app.py
Env vars:  MSD_API_HOST (default 127.0.0.1), MSD_API_PORT (default 8080)
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from flask import Flask, jsonify, render_template, request

# Allow `python src/api/app.py` from anywhere: make src/ importable.
_SRC_DIR = Path(__file__).resolve().parents[1]
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from composition import Components, load_components  # noqa: E402
from ports.config_management_repository import ConfigManagementAccessError  # noqa: E402
from ports.task_runner import ITaskRunner  # noqa: E402

logger = logging.getLogger(__name__)

_SELECTION = ("project_id", "platform_id", "version_id")


def create_app(components: Components = None, task_runner: ITaskRunner = None) -> Flask:
    if components is None:
        components = load_components()
    if task_runner is None:
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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = create_app(load_components())
    host = os.environ.get("MSD_API_HOST", "127.0.0.1")
    port = int(os.environ.get("MSD_API_PORT", "8080"))
    print(f"MSD API on http://{host}:{port}", flush=True)
    app.run(host=host, port=port)


if __name__ == "__main__":
    main()
