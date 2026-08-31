# Digital System Model

## Run the dev containers

```bash
cd dev
docker compose up
```

## Set up the venv

`msd` (DSM-MSD) is a library — clone/generate business logic, no API or
worker of its own. `vae` (DSM-VAE) is the serving layer: it imports msd and
exposes it via a Flask API, a Celery worker, and a UI. Install msd first,
since vae depends on it:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e ./msd -e ./vae
```

Both packages are packaged with a plain `setup.py` (src layout) so the
editable install works on both modern pip and old pip (< 21.3, e.g. stock
Python 3.8 installs); modern pip takes the legacy path and may print a
deprecation warning.

## Start VAE

In one terminal, start the worker:

```bash
vae-worker
```

Optional: set the worker process count with `-c`/`--concurrency`
(default is the CPU count, as per Celery):

```bash
vae-worker -c 4
```

In a second terminal, start the API:

```bash
vae-api
```

Both read the same `vae/src/vae/config.ini` (worker: `[worker]`, API: `[api]`,
plus `[config_mgmt_db]` for project/platform/version selection).
(Equivalent to `python -m vae.worker` / `python -m vae.api`.)

Then open the UI at <http://127.0.0.1:8080>.

### VAE API endpoints

| Method | Path | Description |
| ------ | ---- | ----------- |
| GET | `/` | Single-page UI |
| GET | `/api/projects` | List projects (via msd's config-mgmt repository) |
| GET | `/api/projects/<project_id>/platforms` | List platforms for a project |
| GET | `/api/projects/<project_id>/platforms/<platform_id>/versions` | List versions for a platform |
| POST | `/api/msd/run` | Enqueue msd's clone + generate workflow; body `{"project_id", "platform_id", "version_id"}`, returns `202 {"task_id"}` |
| GET | `/api/msd/tasks/<task_id>/output` | Server-sent run stream (SSE): output lines, `status` events pushed on state changes (with a snapshot on connect/reconnect), and a final `done` event carrying the terminal payload (state/result/error) |
| POST | `/api/msd/tasks/<task_id>/cancel` | Cancel a queued or running task (terminates the worker process if running); returns the task state |

Note: each open run stream holds one API thread for the run's duration
(dev server is threaded by default; size production workers accordingly).

## Run the containers

```bash
docker compose up
```

