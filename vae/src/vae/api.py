"""VAE's Flask API (SRS DSM-VAE req 3-6, minimal slice): authenticates the
user against the LDAP directory service (delegating to vae's auth
repository), lets the user connect to the config_mgmt_db and source_code_repo
data sources with their own credentials, one at a time (delegating to vae's
composition root), select a project/platform/version (delegating to msd's
config-mgmt repository), and trigger + monitor an MSD run (delegating to
msd's Celery task runner).

Flask endpoints:
  GET  /
  GET  /api/session
  POST /api/login                                     body {"username", "password"}
  POST /api/logout
  POST /api/data-sources/connect/config-mgmt-db        body {"connection_address", "username", "password"}  [login required]
  POST /api/data-sources/connect/source-code-repo      body {"connection_address", "username", "password"}  [login + config_mgmt_db connected]
  GET  /api/projects                                                    [login + config_mgmt_db connected]
  GET  /api/projects/<project_id>/platforms                             [login + config_mgmt_db connected]
  GET  /api/projects/<project_id>/platforms/<platform_id>/versions      [login + config_mgmt_db connected]
  GET  /api/projects/<project_id>/platforms/<platform_id>/versions/<version_id>/units  [login + config_mgmt_db connected]
  POST /api/msd/run   body {"project_id", "platform_id", "version_id"}  [login + both data sources connected]
  GET  /api/msd/tasks/<task_id>/output                                 [login required]
  GET  /api/msd/tasks/<task_id>/download                               [login required]
  POST /api/msd/tasks/<task_id>/cancel                                 [login required]

Run with:  vae-api  (or: python -m vae.api)
The API host/port/session secret come from the [api] section of vae's config.ini.
"""

from __future__ import annotations

import functools
import json
import logging
from pathlib import Path
import time

from flask import Flask, Response, jsonify, render_template, request, send_file, session

from msd.domain.data_source import SourceType
from msd.ports.config_management_repository import ConfigManagementAccessError

from vae.composition import Components, load_components
from vae.config import get_config
from vae.task_runner import TaskStatus

logger = logging.getLogger(__name__)

_SELECTION = ("project_id", "platform_id", "version_id")
_CREDENTIALS = ("username", "password")
_CONNECT_FIELDS = ("connection_address", "username", "password")

# Run stream (SSE) pacing: how often a still-running task's output store and
# task status are re-checked, and the hard cap on one stream (leak guard — a
# well-behaved EventSource closes on the `done` event or when the card is
# reset). The stream carries the task's output lines, a `status` event on
# every state change (plus a snapshot on connect/reconnect), and a final
# `done` event carrying the terminal payload.
_OUTPUT_STREAM_TICK_SECONDS = 0.5
_OUTPUT_STREAM_MAX_SECONDS = 3600
_OUTPUT_TERMINAL_STATES = ("SUCCESS", "FAILURE", "REVOKED")


def _status_payload(status: TaskStatus) -> dict:
    """JSON payload for a task status — shared by the REST cancel endpoint
    and the run stream's `status`/`done` events."""
    payload = {"task_id": status.task_id, "state": status.state}
    if status.result is not None:
        payload["result"] = status.result
    if status.error is not None:
        payload["error"] = status.error
    return payload


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if "username" not in session:
            return jsonify({"error": "authentication required"}), 401
        return view(*args, **kwargs)

    return wrapped


def create_app(components: Components = None) -> Flask:
    app = Flask(__name__)
    app.secret_key = get_config().api.secret_key

    if components is None:
        components = load_components()

    def _connections():
        return components.connections.get(session.get("conn_token"), {})

    def config_db_required(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            if SourceType.CONFIG_MGMT_DB not in _connections():
                return jsonify({"error": "config management database connection required"}), 401
            return view(*args, **kwargs)

        return wrapped

    def source_repo_required(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            if SourceType.SOURCE_CODE_REPO not in _connections():
                return jsonify({"error": "source code repo connection required"}), 401
            return view(*args, **kwargs)

        return wrapped

    def _connect_body():
        body = request.get_json(silent=True, force=True)
        if not isinstance(body, dict):
            return None, (jsonify({"error": "request body must be a JSON object"}), 400)
        missing = [field for field in _CONNECT_FIELDS if not body.get(field)]
        if missing:
            return None, (jsonify({"error": f"missing field(s): {', '.join(missing)}"}), 400)
        return body, None

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/login", methods=["POST"])
    def api_login():
        body = request.get_json(silent=True, force=True)
        if not isinstance(body, dict):
            return jsonify({"error": "request body must be a JSON object"}), 400
        missing = [key for key in _CREDENTIALS if not body.get(key)]
        if missing:
            return jsonify({"error": f"missing field(s): {', '.join(missing)}"}), 400
        user = components.authenticate_user().execute(body["username"], body["password"])
        if user is None:
            return jsonify({"error": "invalid username or password"}), 401
        session["username"] = user.username
        session["role"] = user.role.value
        return jsonify({
            "username": user.username,
            "role": user.role.value,
            "defaults": {
                "config_mgmt_db": components.defaults[SourceType.CONFIG_MGMT_DB].connection_address,
                "source_code_repo": components.defaults[SourceType.SOURCE_CODE_REPO].connection_address,
            },
        })

    @app.route("/api/session")
    def api_session():
        if "username" not in session:
            return jsonify({"authenticated": False})
        connections = _connections()
        return jsonify({
            "authenticated": True,
            "username": session["username"],
            "role": session.get("role"),
            "defaults": {
                "config_mgmt_db": components.defaults[SourceType.CONFIG_MGMT_DB].connection_address,
                "source_code_repo": components.defaults[SourceType.SOURCE_CODE_REPO].connection_address,
            },
            "config_mgmt_db_connected": SourceType.CONFIG_MGMT_DB in connections,
            "source_code_repo_connected": SourceType.SOURCE_CODE_REPO in connections,
        })

    @app.route("/api/logout", methods=["POST"])
    def api_logout():
        components.connections.pop(session.get("conn_token"), None)
        session.clear()
        return "", 204

    @app.route("/api/data-sources/connect/config-mgmt-db", methods=["POST"])
    @login_required
    def api_connect_config_mgmt_db():
        body, error = _connect_body()
        if error:
            return error
        try:
            token = components.connect_config_mgmt_db(body)
        except ConfigManagementAccessError as exc:
            return jsonify({"error": str(exc)}), 502
        session["conn_token"] = token
        return jsonify({"connected": True})

    @app.route("/api/data-sources/connect/source-code-repo", methods=["POST"])
    @login_required
    @config_db_required
    def api_connect_source_repo():
        body, error = _connect_body()
        if error:
            return error
        components.connect_source_repo(session["conn_token"], body)
        return jsonify({"connected": True})

    @app.route("/api/projects")
    @login_required
    @config_db_required
    def api_projects():
        config_repo = components.config_repo_factory(_connections()[SourceType.CONFIG_MGMT_DB])
        try:
            projects = config_repo.list_projects()
        except ConfigManagementAccessError as exc:
            return jsonify({"error": str(exc)}), 502
        return jsonify({"projects": [p.to_dict() for p in projects]})

    @app.route("/api/projects/<project_id>/platforms")
    @login_required
    @config_db_required
    def api_platforms(project_id):
        config_repo = components.config_repo_factory(_connections()[SourceType.CONFIG_MGMT_DB])
        try:
            platforms = config_repo.list_platforms(project_id)
        except ConfigManagementAccessError as exc:
            return jsonify({"error": str(exc)}), 502
        return jsonify({"platforms": [p.to_dict() for p in platforms]})

    @app.route("/api/projects/<project_id>/platforms/<platform_id>/versions")
    @login_required
    @config_db_required
    def api_versions(project_id, platform_id):
        config_repo = components.config_repo_factory(_connections()[SourceType.CONFIG_MGMT_DB])
        try:
            versions = config_repo.list_versions(project_id, platform_id)
        except ConfigManagementAccessError as exc:
            return jsonify({"error": str(exc)}), 502
        return jsonify({"versions": [v.to_dict() for v in versions]})

    @app.route("/api/projects/<project_id>/platforms/<platform_id>/versions/<version_id>/units")
    @login_required
    @config_db_required
    def api_units(project_id, platform_id, version_id):
        config_repo = components.config_repo_factory(_connections()[SourceType.CONFIG_MGMT_DB])
        try:
            units = config_repo.list_unit_versions(project_id, platform_id, version_id)
        except ConfigManagementAccessError as exc:
            return jsonify({"error": str(exc)}), 502
        return jsonify({"units": [u.to_dict() for u in units]})

    @app.route("/api/msd/run", methods=["POST"])
    @login_required
    @config_db_required
    @source_repo_required
    def api_msd_run():
        body = request.get_json(silent=True, force=True)
        if not isinstance(body, dict):
            return jsonify({"error": "request body must be a JSON object"}), 400
        missing = [key for key in _SELECTION if not body.get(key)]
        if missing:
            return jsonify({"error": f"missing field(s): {', '.join(missing)}"}), 400
        connections = _connections()
        config_mgmt = connections[SourceType.CONFIG_MGMT_DB]
        source_repo = connections[SourceType.SOURCE_CODE_REPO]
        config_mgmt_username, _, config_mgmt_password = config_mgmt.user_info.partition(":")
        source_repo_username, _, source_repo_password = source_repo.user_info.partition(":")
        try:
            task_id = components.msd_task_runner.submit_run(
                body["project_id"], body["platform_id"], body["version_id"],
                config_mgmt.connection_address, config_mgmt_username, config_mgmt_password,
                source_repo.connection_address, source_repo_username, source_repo_password,
            )
        except Exception as exc:
            logger.warning("msd/run: task submission failed: %s", exc)
            return jsonify({"error": str(exc)}), 502
        return jsonify({"task_id": task_id}), 202

    @app.route("/api/msd/tasks/<task_id>/cancel", methods=["POST"])
    @login_required
    def api_msd_task_cancel(task_id):
        try:
            status = components.msd_task_runner.cancel(task_id)
        except Exception as exc:
            logger.warning("msd/tasks/%s: cancellation failed: %s", task_id, exc)
            return jsonify({"error": str(exc)}), 502
        return jsonify(_status_payload(status))

    @app.route("/api/msd/tasks/<task_id>/download")
    @login_required
    def api_msd_task_download(task_id):
        output_path = (components.msd_task_runner.status(task_id).result or {}).get("output_path")
        if not output_path:
            return jsonify({"error": "run has no output file"}), 404
        path = Path(output_path)
        if not path.is_file():
            return jsonify({"error": "output file not found"}), 404
        return send_file(
            path,
            mimetype="application/json",
            as_attachment=True,
            download_name=path.name,
        )

    @app.route("/api/msd/tasks/<task_id>/output")
    @login_required
    def api_msd_task_output(task_id):
        # EventSource reconnects after a dropped stream carrying the last
        # event id it processed, so the stream resumes at that line instead
        # of replaying what the client already has.
        try:
            cursor = int(request.headers.get("Last-Event-ID") or 0)
        except ValueError:
            cursor = 0

        def stream():
            nonlocal cursor
            deadline = time.monotonic() + _OUTPUT_STREAM_MAX_SECONDS
            last_state = None
            while time.monotonic() < deadline:
                try:
                    lines = components.task_output_store.lines(task_id)
                    status = components.msd_task_runner.status(task_id)
                except Exception:
                    # A store/status blip skips this tick; the stream stays up.
                    time.sleep(_OUTPUT_STREAM_TICK_SECONDS)
                    continue
                for index, line in enumerate(lines[cursor:], start=cursor):
                    yield f"id: {index}\ndata: {line}\n\n"
                    cursor = index + 1
                # No `id:` on status/done events — state isn't resumable, a
                # reconnect gets a fresh snapshot (last_state starts None).
                if status.state != last_state:
                    last_state = status.state
                    yield f"event: status\ndata: {json.dumps(_status_payload(status))}\n\n"
                if status.state in _OUTPUT_TERMINAL_STATES:
                    yield f"event: done\ndata: {json.dumps(_status_payload(status))}\n\n"
                    return
                time.sleep(_OUTPUT_STREAM_TICK_SECONDS)

        return Response(
            stream(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = create_app(load_components())
    api = get_config().api
    print(f"VAE API on http://{api.host}:{api.port}", flush=True)
    app.run(host=api.host, port=api.port)


if __name__ == "__main__":
    main()
