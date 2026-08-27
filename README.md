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

In a terminal, start the worker:

```bash
cd msd/src
python3.9 -m celery -A tasks.celery_app worker --loglevel=info
```

In a second terminal, start the API:

```bash
python3.9 msd/src/api/app.py
```

Then open the UI at <http://127.0.0.1:8080>.

## Run the containers

```bash
docker compose up
```
