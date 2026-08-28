"""Celery worker: the Celery app (configured from the [worker] section of
config.ini) and the msd.run_msd_workflow task.

Run from msd/, in the same venv, using the same config.ini as the API:
  python worker.py [-c N]
(-c N sets the prefork process count, e.g. `python worker.py -c 4`;
default is the CPU count, as per Celery)
(equivalent: celery -A worker worker --loglevel=info)
"""

import argparse

from celery import Celery

from composition import load_components
from config import get_config

RESULT_EXPIRES_SECONDS = 86400


def make_celery() -> Celery:
    """Create the Celery app from the [worker] section of config.ini."""
    config = get_config()
    celery_app = Celery("msd")
    celery_app.config_from_object(
        {
            "broker_url": config.worker.broker_url,
            "result_backend": config.worker.result_backend,
            "result_expires": RESULT_EXPIRES_SECONDS,
            "task_track_started": True,
            "task_serializer": "json",
            "result_serializer": "json",
            "accept_content": ["json"],
        }
    )
    return celery_app


celery_app = make_celery()


@celery_app.task(bind=True, name="msd.run_msd_workflow")
def run_msd_workflow(self, project_id: str, platform_id: str, version_id: str) -> dict:
    """Full MSD workflow for one selection, in a workspace dir keyed by this
    task's id: all artifacts (cloned unit repositories and
    model_setup_data.json) live under <workspace>/<task_id>/<project>/<platform>/<version>."""
    components = load_components()
    return components.workflow().execute(
        components.workspace / self.request.id, project_id, platform_id, version_id
    ).to_dict()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the MSD Celery worker (config from config.ini).")
    parser.add_argument(
        "-c",
        "--concurrency",
        type=int,
        default=None,
        metavar="N",
        help="worker process count (default: CPU count, as per Celery)",
    )
    args = parser.parse_args()
    argv = ["worker", "--loglevel=info"]
    if args.concurrency is not None:
        argv.append(f"--concurrency={args.concurrency}")
    celery_app.worker_main(argv)


if __name__ == "__main__":
    main()
