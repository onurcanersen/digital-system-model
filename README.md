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

Sessions are persistent (the cookie carries a 24h lifetime, the same window a
tracked run is kept for): closing the browser — even mid-run — and reopening
it resumes the same session on the card the user was standing on, with the
run's output replayed from the store.

### VAE API endpoints

| Method | Path | Description |
| ------ | ---- | ----------- |
| GET | `/` | Single-page UI |
| GET | `/api/session` | Session state for resume: auth, data-source connection flags, persisted selection, the tracked run (task id + its selection snapshot + submission time; dropped once past the worker's result expiry), and the UI record below |
| POST | `/api/session/ui` | Record where the user is standing so a reload can put them back: body `{"view", "model_file"?, "candidate"?}` — the card on screen, the run id of the produced file the Core System Model card is showing, and a candidate chosen but not yet run. Scoped to the selection, and dropped with it |
| GET | `/api/projects` | List projects (via msd's config-mgmt repository) |
| GET | `/api/projects/<project_id>/platforms` | List platforms for a project |
| GET | `/api/projects/<project_id>/platforms/<platform_id>/versions` | List versions for a platform |
| GET | `/api/projects/.../versions/<version_id>/units` | Software Unit Version Inventory for a selection |
| GET | `/api/projects/.../versions/<version_id>/msd-files` | List the Model Setup Data files produced for a selection, newest first (run id, producer, timestamp, model scale, candidate version if the run evaluated one) |
| GET | `/api/projects/.../versions/<version_id>/msd-files/<run_id>/model` | Serve one produced file inline (the Core System Model card reads this) |
| GET | `/api/projects/.../versions/<version_id>/msd-files/<run_id>/download` | Serve one produced file as an attachment |
| GET | `/api/units/<unit_name>/versions` | Versions the source code repository publishes for a software unit (its tags, newest first) — the set a candidate version is chosen from |
| POST | `/api/selection` | Persist the selected project/platform/version in the session; body `{"project_id", "platform_id", "version_id"}` |
| DELETE | `/api/selection` | Clear the persisted selection (the UI clears it on resume when the options no longer exist) |
| POST | `/api/msd/run` | Enqueue msd's clone + generate workflow; body `{"project_id", "platform_id", "version_id"}` plus an optional `"candidate": {"unit_name", "version"}`, returns `202 {"task_id"}` |
| GET | `/api/msd/tasks/<task_id>` | One poll of the run: the task's status (state, and result/error/progress when the run has published them) plus the output lines after the `after` cursor — the index of the last line the client holds, absent for the full list. The UI polls it every second or so until the state goes terminal; it is the machine-readable status channel for automation clients too |
| POST | `/api/msd/tasks/<task_id>/cancel` | Cancel a queued or running task (terminates the worker process if running); returns the task state |

The run card follows the run by polling `GET /api/msd/tasks/<task_id>` every
second or so; a poll is a short request (task status plus the output lines
after the client's cursor), so nothing stays open for the run's duration.

Produced files are addressed by selection + run id (the run id being the task
id of the run that produced them), never through the task runner: a task's
execution record expires after 24h, the artifact it wrote does not. On disk
that is `<msd workspace>/<project>/<platform>/<version>/<run_id>/model_setup_data.json`,
and the file records which user produced it.

A run may name one **candidate version** — the version of a software unit being
evaluated for installation into the target environment (SRS DSM-MSD req 11). The
run then acquires and records that version for that unit, alongside the other
units at the versions the selected system version defines, and the produced
file's Software Unit Version Inventory flags it as the candidate. The versions
on offer come from the unit's source repository rather than the configuration
management database, since a candidate is by definition a version no system
version defines yet — specifically its tags, which is how a unit publishes a
version (see `dev/gitea/seed.sh`) and the same ref the clone asks git for.

## Run the containers

```bash
docker compose up
```

