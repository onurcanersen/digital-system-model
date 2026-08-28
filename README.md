# Digital System Model

## Run the dev containers

```bash
cd dev
docker compose up
```

## Set up the venv

```bash
python3.9 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Start MSD

In one terminal, start the worker:

```bash
cd msd
python worker.py
```

Optional: set the worker process count with `-c`/`--concurrency`
(default is the CPU count, as per Celery):

```bash
cd msd
python worker.py -c 4
```

In a second terminal, start the API:

```bash
cd msd
python api.py
```

Both read the same `config.ini` (worker: `[worker]`, API: `[api]`).

Then open the UI at <http://127.0.0.1:8080>.

### API endpoints

| Method | Path | Description |
| ------ | ---- | ----------- |
| GET | `/` | Single-page UI |
| GET | `/api/projects` | List projects |
| GET | `/api/projects/<project_id>/platforms` | List platforms for a project |
| GET | `/api/projects/<project_id>/platforms/<platform_id>/versions` | List versions for a platform |
| GET | `/api/projects/<project_id>/platforms/<platform_id>/versions/<version_id>/units` | List unit versions for a selection |
| POST | `/api/run` | Enqueue clone + generate; body `{"project_id", "platform_id", "version_id"}`, returns `202 {"task_id", "status_url"}` |
| GET | `/api/tasks/<task_id>` | Task state, result or error |

## Run the containers

```bash
docker compose up
```
