"""VAE's Flask API (SRS DSM-VAE req 3-6, minimal slice): authenticates the
user against the LDAP directory service (delegating to vae's auth
repository), lets the user connect to the config_mgmt_db and source_code_repo
data sources with their own credentials, in either order (delegating to vae's
composition root), select a project/platform/version (delegating to msd's
config-mgmt repository), and trigger + monitor an MSD run (delegating to
msd's Celery task runner).

Flask endpoints:
  GET  /
  GET  /api/session
  POST /api/session/ui  body {"view", "model_file"?, "candidate"?}          [login required]
  POST /api/login                                     body {"username", "password"}
  POST /api/logout
  POST /api/data-sources/connect/config-mgmt-db        body {"connection_address", "username", "password"}  [login required]
  POST /api/data-sources/connect/source-code-repo      body {"connection_address", "username", "password"}  [login required]
  POST /api/selection   body {"project_id", "platform_id", "version_id"}  [login + config_mgmt_db connected]
  DELETE /api/selection                                                    [login + config_mgmt_db connected]
  GET  /api/projects                                                    [login + config_mgmt_db connected]
  GET  /api/projects/<project_id>/platforms                             [login + config_mgmt_db connected]
  GET  /api/projects/<project_id>/platforms/<platform_id>/versions      [login + config_mgmt_db connected]
  GET  /api/projects/<project_id>/platforms/<platform_id>/versions/<version_id>/units  [login + config_mgmt_db connected]
  GET  /api/projects/.../versions/<version_id>/msd-files                    [login + config_mgmt_db connected]
  GET  /api/projects/.../versions/<version_id>/msd-files/<run_id>/model     [login + config_mgmt_db connected]
  GET  /api/projects/.../versions/<version_id>/msd-files/<run_id>/download  [login + config_mgmt_db connected]
  GET  /api/units/<unit_name>/versions                                 [login + source_code_repo connected]
  POST /api/msd/run   body {"project_id", "platform_id", "version_id",
                            "candidate"?: {"unit_name", "version"}}  [login + both data sources connected]
  GET  /api/msd/tasks/<task_id>/output                                 [login required]
  POST /api/msd/tasks/<task_id>/cancel                                 [login required]

Produced files are addressed by selection + run id (the run id being the task
id of the run that produced them), not through the task runner — a task's
execution record expires after RESULT_EXPIRES_SECONDS, the artifact it wrote
does not.

Run with:  vae-api  (or: python -m vae.api)
The API host/port/session secret come from the [api] section of vae's config.ini.
"""

from __future__ import annotations

import functools
import json
import logging
import time

from flask import Flask, Response, jsonify, render_template, request, send_file, session

from msd.domain.data_source import SourceType
from msd.ports.config_management_repository import ConfigManagementAccessError
from msd.ports.source_code_repository import SourceRepoAccessError, SourceRepoAuthError

from vae.composition import Components, load_components
from vae.config import get_config
from vae.domain.task_status import TaskStatus
from vae.worker import RESULT_EXPIRES_SECONDS

logger = logging.getLogger(__name__)

_SELECTION = ("project_id", "platform_id", "version_id")
_CREDENTIALS = ("username", "password")
_CONNECT_FIELDS = ("connection_address", "username", "password")
_CANDIDATE_FIELDS = ("unit_name", "version")

# The cards a reload can land back on. The UI is one page with no addresses of
# its own, so where the user was standing is session state like the selection
# is — and, like it, it is only ever restored into a UI that already agrees
# with the server about everything else. `boot` and `login` are absent
# deliberately: neither is a place to come back to.
_RESUMABLE_VIEWS = ("sources", "select", "inventory", "files", "run", "model")

# Run stream (SSE) pacing: how often a still-running task's output store and
# task status are re-checked, the hard cap on one stream, and the grace window
# after a run has ended. The stream carries the task's output lines, a `status`
# event on every state change (plus a snapshot on connect/reconnect), and a
# `ping` every PING_SECONDS of silence. The terminal `status` is the
# terminator: the client closes the stream on it, and the server keeps the
# connection open for TERMINAL_GRACE_SECONDS afterwards as a leak guard
# (a client that vanished is detected on the next failed ping write) rather
# than closing it itself — a server-side close in the same instant as the
# final events lets proxies deliver the close before the bytes, which reads
# to the client as a mid-run drop.
#
# A real run goes quiet for minutes at a time (source analysis logs once per
# unit and nothing in between), and an SSE connection that carries no bytes
# for that long is dropped by whatever sits on the path — without a FIN the
# browser never fires `error`, so EventSource never reconnects and the run
# card is stranded mid-run. So the stream says something on every ping
# interval whether or not the task did: a named event rather than a `:`
# comment, because the client watchdog has to be able to see it (comments
# keep the socket warm but never reach JavaScript).
_OUTPUT_STREAM_TICK_SECONDS = 0.5
_OUTPUT_STREAM_PING_SECONDS = 15
_OUTPUT_STREAM_MAX_SECONDS = 3600
_OUTPUT_STREAM_TERMINAL_GRACE_SECONDS = 60
_OUTPUT_STREAM_TERMINAL_PING_SECONDS = 5
_OUTPUT_TERMINAL_STATES = ("SUCCESS", "FAILURE", "REVOKED")


def _status_payload(status: TaskStatus) -> dict:
    """JSON payload for a task status — shared by the REST cancel endpoint
    and the run stream's `status` events (a terminal one ends the run)."""
    payload = {"task_id": status.task_id, "state": status.state}
    if status.result is not None:
        payload["result"] = status.result
    if status.error is not None:
        payload["error"] = status.error
    return payload


def _candidate_from(body: dict):
    """The optional candidate unit version a run is evaluating (SRS DSM-MSD
    req 11), as (candidate, error_response). Absent is not an error — most
    runs describe the versions the selected system version defines — but a
    malformed one is refused here rather than reaching the worker, where a
    silently dropped candidate would produce a run of the wrong versions."""
    candidate = body.get("candidate")
    if candidate is None:
        return None, None
    if not isinstance(candidate, dict):
        return None, (jsonify({"error": "candidate must be a JSON object"}), 400)
    missing = [key for key in _CANDIDATE_FIELDS if not candidate.get(key)]
    if missing:
        return None, (jsonify({"error": f"candidate missing field(s): {', '.join(missing)}"}), 400)
    return {key: candidate[key] for key in _CANDIDATE_FIELDS}, None


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

    def _msd_file(project_id, platform_id, version_id, run_id):
        """The model_setup_data.json one run produced, or a 404 response.
        Shared by the download and the model endpoints — the same file, served
        two ways.

        Addressed by selection + run id rather than through the task runner's
        result: an execution record expires, the artifact does not, so a file
        stays reachable for as long as it is on disk."""
        path = components.msd_catalog.resolve(project_id, platform_id, version_id, run_id)
        if path is None:
            return None, (jsonify({"error": "model setup data file not found"}), 404)
        return path, None

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
        active_task = session.get("active_task")
        if (
            active_task is not None
            and time.time() - active_task["submitted_at"] > RESULT_EXPIRES_SECONDS
        ):
            # Past Celery's result expiry the backend holds neither the task's
            # state nor its result, so the run is untrackable from the UI.
            session.pop("active_task", None)
            active_task = None
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
            "selection": session.get("selection"),
            "active_task": active_task,
            "ui": session.get("ui"),
        })

    @app.route("/api/session/ui", methods=["POST"])
    @login_required
    def api_set_ui():
        body = request.get_json(silent=True, force=True)
        if not isinstance(body, dict):
            return jsonify({"error": "request body must be a JSON object"}), 400
        view = body.get("view")
        if view not in _RESUMABLE_VIEWS:
            return jsonify({
                "error": f"view must be one of: {', '.join(_RESUMABLE_VIEWS)}"
            }), 400
        candidate, error = _candidate_from(body)
        if error is not None:
            return error
        session["ui"] = {
            "view": view,
            # The produced file the Model card is showing, by the run id that
            # addresses it under the current selection. The file itself is not
            # stored: it outlives the session, and the listing is read fresh.
            "model_file": body.get("model_file") or None,
            # A candidate chosen but not yet run. Once a run is submitted the
            # run's own record is the authority on what it is evaluating.
            "candidate": candidate,
        }
        return "", 204

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
        # The slot is claimed before the attempt, so a refused credential
        # reuses it on the next try rather than stranding an empty one.
        session["conn_token"] = token = components.open_token(session.get("conn_token"))
        try:
            components.connect_config_mgmt_db(token, body)
        except ConfigManagementAccessError as exc:
            return jsonify({"error": str(exc)}), 502
        # A selection belongs to this config-mgmt-DB connection's epoch; a new
        # connection (possibly to a different database) invalidates it. Any
        # other source connected in this session is untouched — the sources
        # are peers, and only the selection came out of this one.
        session.pop("selection", None)
        # Everything the UI record holds is addressed by that selection — the
        # produced file, the candidate, and the cards that presuppose a
        # context — so it goes with it.
        session.pop("ui", None)
        return jsonify({"connected": True})

    @app.route("/api/data-sources/connect/source-code-repo", methods=["POST"])
    @login_required
    def api_connect_source_repo():
        body, error = _connect_body()
        if error:
            return error
        session["conn_token"] = token = components.open_token(session.get("conn_token"))
        components.connect_source_repo(token, body)
        return jsonify({"connected": True})

    @app.route("/api/selection", methods=["POST"])
    @login_required
    @config_db_required
    def api_set_selection():
        body = request.get_json(silent=True, force=True)
        if not isinstance(body, dict):
            return jsonify({"error": "request body must be a JSON object"}), 400
        missing = [key for key in _SELECTION if not body.get(key)]
        if missing:
            return jsonify({"error": f"missing field(s): {', '.join(missing)}"}), 400
        selection = {key: body[key] for key in _SELECTION}
        # Re-confirming the same selection is not a change of context: the file
        # on show and the candidate still describe it, so they stay. A
        # different one leaves them describing nothing.
        if selection != session.get("selection"):
            session.pop("ui", None)
        session["selection"] = selection
        return jsonify({"selection": selection})

    @app.route("/api/selection", methods=["DELETE"])
    @login_required
    @config_db_required
    def api_clear_selection():
        session.pop("selection", None)
        session.pop("ui", None)
        return "", 204

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

    @app.route("/api/units/<unit_name>/versions")
    @login_required
    @source_repo_required
    def api_unit_versions(unit_name):
        """The versions the source repository holds for one software unit —
        the set a candidate version is chosen from (SRS DSM-MSD req 11).

        Not nested under a selection: the repository is keyed by unit name
        alone, and a candidate is precisely a version no system version
        defines yet, so scoping it by one would be a fiction."""
        source_repo = components.source_repo_factory(_connections()[SourceType.SOURCE_CODE_REPO])
        try:
            versions = source_repo.list_available_versions(unit_name)
        except (SourceRepoAccessError, SourceRepoAuthError) as exc:
            return jsonify({"error": str(exc)}), 502
        return jsonify({"versions": versions})

    @app.route("/api/projects/<project_id>/platforms/<platform_id>/versions/<version_id>/msd-files")
    @login_required
    @config_db_required
    def api_msd_files(project_id, platform_id, version_id):
        # Scoped by project/platform/version, not by user (SRS DSM-VAE req 5):
        # a Model Setup Data file belongs to the selection it describes, and
        # every signed-in user working that selection sees every file for it.
        # Who produced each one rides along in the record instead.
        records = components.msd_catalog.list(project_id, platform_id, version_id)
        return jsonify({"files": [r.to_dict() for r in records]})

    @app.route(
        "/api/projects/<project_id>/platforms/<platform_id>/versions/<version_id>"
        "/msd-files/<run_id>/model"
    )
    @login_required
    @config_db_required
    def api_msd_file_model(project_id, platform_id, version_id, run_id):
        # Inline: the Core System Model card reads it with fetch, and an
        # attachment would be saved instead.
        path, error = _msd_file(project_id, platform_id, version_id, run_id)
        if error is not None:
            return error
        return send_file(path, mimetype="application/json", as_attachment=False)

    @app.route(
        "/api/projects/<project_id>/platforms/<platform_id>/versions/<version_id>"
        "/msd-files/<run_id>/download"
    )
    @login_required
    @config_db_required
    def api_msd_file_download(project_id, platform_id, version_id, run_id):
        path, error = _msd_file(project_id, platform_id, version_id, run_id)
        if error is not None:
            return error
        return send_file(
            path,
            mimetype="application/json",
            as_attachment=True,
            download_name=path.name,
        )

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
        candidate, error = _candidate_from(body)
        if error is not None:
            return error
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
                # Recorded inside the produced file, so the listing can say who
                # produced it long after this session is gone.
                produced_by=session["username"],
                # Likewise recorded in the file's inventory, which is what
                # tells two runs of one selection apart in a listing.
                candidate=candidate,
            )
        except Exception as exc:
            logger.warning("msd/run: task submission failed: %s", exc)
            return jsonify({"error": str(exc)}), 502
        # The UI re-attaches to this run after a refresh/reload (its output
        # stream replays the stored lines plus a status snapshot). The task's
        # own selection snapshot — and the candidate it is evaluating — rides
        # along so the run card can describe it even if the user's saved
        # selection changes before the reload.
        session["active_task"] = {
            "task_id": task_id,
            "project_id": body["project_id"],
            "platform_id": body["platform_id"],
            "version_id": body["version_id"],
            "candidate": candidate,
            "submitted_at": time.time(),
        }
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

    @app.route("/api/msd/tasks/<task_id>/output")
    @login_required
    def api_msd_task_output(task_id):
        # A client that reopens the stream itself (its own re-dial after a
        # drop) says where to resume in the query string — only the browser's
        # native reconnect would set Last-Event-ID, and the client closes the
        # source on error so it no longer happens. Resuming at the line after
        # the id the client last received means nothing it already has is
        # replayed.
        resume = request.args.get("last_event_id")
        try:
            # Clamped: a negative id would slice from the end of the log and
            # replay the tail as if it were the head.
            cursor = max(0, int(resume) + 1)
        except (TypeError, ValueError):
            cursor = 0

        def stream():
            nonlocal cursor
            now = time.monotonic()
            deadline = now + _OUTPUT_STREAM_MAX_SECONDS
            last_written = now
            last_state = None
            terminal_at = None
            while time.monotonic() < deadline:
                try:
                    lines = components.task_output_store.lines(task_id)
                    # The state is already known terminal in the grace phase,
                    # so the task runner is only asked while the run is going.
                    if terminal_at is None:
                        status = components.msd_task_runner.status(task_id)
                except Exception:
                    # A store/status blip skips this tick; the stream stays up.
                    time.sleep(_OUTPUT_STREAM_TICK_SECONDS)
                    continue
                # No `id:` on status/ping events — none of them is resumable,
                # and a reconnect gets a fresh snapshot of the state anyway
                # (last_state starts None).
                for index, line in enumerate(lines[cursor:], start=cursor):
                    yield f"id: {index}\ndata: {line}\n\n"
                    cursor = index + 1
                    last_written = time.monotonic()
                if terminal_at is None and status.state != last_state:
                    last_state = status.state
                    yield f"event: status\ndata: {json.dumps(_status_payload(status))}\n\n"
                    last_written = time.monotonic()
                    if status.state in _OUTPUT_TERMINAL_STATES:
                        # The terminal status is the terminator: the client
                        # closes on it. The server does not close here — it
                        # keeps the stream open (lines only, faster pings)
                        # until the client does or the grace elapses, so the
                        # final events always ride a connection nobody is
                        # tearing down.
                        terminal_at = time.monotonic()
                if terminal_at is not None:
                    if time.monotonic() - last_written >= _OUTPUT_STREAM_TERMINAL_PING_SECONDS:
                        yield "event: ping\ndata: {}\n\n"
                        last_written = time.monotonic()
                    if time.monotonic() - terminal_at >= _OUTPUT_STREAM_TERMINAL_GRACE_SECONDS:
                        return
                elif time.monotonic() - last_written >= _OUTPUT_STREAM_PING_SECONDS:
                    yield "event: ping\ndata: {}\n\n"
                    last_written = time.monotonic()
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
