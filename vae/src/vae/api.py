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
  GET  /api/msd/tasks/<task_id>                                        [login required]

Run with:  vae-api  (or: python -m vae.api)
The API host/port/session secret come from the [api] section of vae's config.ini.
"""

from __future__ import annotations

import functools
import logging

from flask import Flask, jsonify, render_template, request, session

from msd.domain.data_source import SourceType
from msd.ports.config_management_repository import ConfigManagementAccessError

from vae.composition import Components, load_components
from vae.config import get_config

logger = logging.getLogger(__name__)

_SELECTION = ("project_id", "platform_id", "version_id")
_CREDENTIALS = ("username", "password")
_CONNECT_FIELDS = ("connection_address", "username", "password")


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
        return jsonify({"task_id": task_id, "status_url": f"/api/msd/tasks/{task_id}"}), 202

    @app.route("/api/msd/tasks/<task_id>")
    @login_required
    def api_msd_task_status(task_id):
        status = components.msd_task_runner.status(task_id)
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
    print(f"VAE API on http://{api.host}:{api.port}", flush=True)
    app.run(host=api.host, port=api.port)


if __name__ == "__main__":
    main()
