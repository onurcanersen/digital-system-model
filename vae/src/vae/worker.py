"""VAE's Celery worker: the Celery app (configured from vae's own [worker]
section of config.ini) and the run_msd_workflow task, which builds msd's
config-mgmt/source-repo adapters from the credentials supplied by the caller
(vae's /api/msd/run, threading through what the user entered in the
post-login "connect data sources" step) and runs msd's clone + generate
workflow (msd.composition.load_components(...).workflow()). vae is the sole
serving layer for this — msd is a library with no worker process, Celery
app, or data-source credentials of its own.

Run with:  vae-worker [-c N]
(-c N sets the prefork process count, e.g. `vae-worker -c 4`;
default is the CPU count, as per Celery)
(equivalent: python -m vae.worker; celery -A vae.worker worker --loglevel=info)
"""

import argparse

from celery import Celery

from msd.adapters.mysql_config_management_repository import MysqlConfigManagementRepository
from msd.adapters.source_code.git_source_code_repository import GitSourceCodeRepository
from msd.composition import load_components
from msd.config import get_config as get_msd_config
from msd.domain.data_source import DataSourceConfig, SourceType

from vae.config import get_config

RESULT_EXPIRES_SECONDS = 86400


def make_celery() -> Celery:
    """Create the Celery app from the [worker] section of vae's config.ini."""
    config = get_config()
    celery_app = Celery("vae")
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


@celery_app.task(bind=True, name="vae.run_msd_workflow")
def run_msd_workflow(
    self,
    project_id: str,
    platform_id: str,
    version_id: str,
    config_mgmt_address: str,
    config_mgmt_username: str,
    config_mgmt_password: str,
    source_repo_address: str,
    source_repo_username: str,
    source_repo_password: str,
) -> dict:
    """Full MSD workflow for one selection, in a workspace dir keyed by this
    task's id: all artifacts (cloned unit repositories and
    model_setup_data.json) live under <msd workspace>/<task_id>/<project>/<platform>/<version>.

    Connects to config_mgmt_db and source_code_repo with the credentials the
    user supplied at login time, rather than any static config — msd itself
    no longer holds connection info for either."""
    vae_defaults = {c.source_type: c for c in get_config().data_sources}

    config_mgmt_ds = DataSourceConfig(
        source_type=SourceType.CONFIG_MGMT_DB,
        source_name=vae_defaults[SourceType.CONFIG_MGMT_DB].source_name,
        access_method=vae_defaults[SourceType.CONFIG_MGMT_DB].access_method,
        connection_address=config_mgmt_address,
        user_info=f"{config_mgmt_username}:{config_mgmt_password}",
    )
    config_repo = MysqlConfigManagementRepository.from_data_source_config(config_mgmt_ds)

    source_repo_ds = DataSourceConfig(
        source_type=SourceType.SOURCE_CODE_REPO,
        source_name=vae_defaults[SourceType.SOURCE_CODE_REPO].source_name,
        access_method=vae_defaults[SourceType.SOURCE_CODE_REPO].access_method,
        connection_address=source_repo_address,
        user_info=f"{source_repo_username}:{source_repo_password}",
    )
    source_repo = GitSourceCodeRepository.from_data_source_config(
        source_repo_ds, get_msd_config().analyzer.makefile_include_patterns
    )

    components = load_components(config_repo=config_repo, source_repo=source_repo)
    return components.workflow().execute(
        components.workspace / self.request.id, project_id, platform_id, version_id
    ).to_dict()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run VAE's Celery worker (config from config.ini).")
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
