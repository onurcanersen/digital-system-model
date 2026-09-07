"""Composition root for VAE: builds VAE's own config-mgmt repository factory
(by reusing msd's adapter directly, SRS DSM-VAE req 2, 4-5), VAE's own
Celery-backed task runner (adapters/celery_task_runner.py), which
triggers/tracks vae's own run_msd_workflow task — msd itself has no
API/worker/task of its own
(see msd.composition.load_components, which that task calls into) — and
VAE's own auth repository (SRS DSM-VAE req 3).

VAE owns the sole config.ini for data-source connection *addresses*
(config_mgmt_db, source_code_repo — msd no longer keeps its own copy).
Credentials are never defaulted from that file: they're supplied by the
user on the post-login "sources" step, one tile per data source (api.py's
/api/data-sources/connect/config-mgmt-db and /connect/source-code-repo),
and held only in-memory, per session, here in `Components.connections`.
The two sources are peers: either may be connected first, and connecting
one leaves the other alone. One session owns one slot in `connections`,
keyed by the token `open_token` hands out.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Callable, Dict

from msd.adapters.filesystem_model_setup_data_catalog import FilesystemModelSetupDataCatalog
from msd.adapters.mysql_config_management_repository import MysqlConfigManagementRepository
from msd.adapters.source_code.git_source_code_repository import GitSourceCodeRepository
from msd.composition import workspace_root
from msd.config import get_config as get_msd_config
from msd.domain.data_source import DataSourceConfig, SourceType
from msd.ports.config_management_repository import IConfigManagementRepository
from msd.ports.model_setup_data_catalog import IModelSetupDataCatalog
from msd.ports.source_code_repository import ISourceCodeRepository

from vae.adapters.celery_task_runner import CeleryTaskRunner
from vae.adapters.ldap_auth_repository import LdapAuthRepository
from vae.adapters.redis_task_output_store import RedisTaskOutputStore
from vae.config import DEFAULT_CONFIG_PATH, get_config
from vae.ports.auth_repository import IAuthRepository
from vae.ports.task_output_store import ITaskOutputStore
from vae.ports.task_runner import ITaskRunner
from vae.services.authenticate_user import AuthenticateUser


@dataclass
class Components:
    defaults: Dict[SourceType, DataSourceConfig]
    config_repo_factory: Callable[[DataSourceConfig], IConfigManagementRepository]
    # Peer of config_repo_factory, for the reads the API serves out of the
    # source repository itself rather than the configuration management
    # database — the versions a unit has published, which is where a candidate
    # version is chosen from (SRS DSM-MSD req 11). Built per request from the
    # session's own credentials, exactly as the worker builds its own.
    source_repo_factory: Callable[[DataSourceConfig], ISourceCodeRepository]
    msd_task_runner: ITaskRunner
    auth_repo: IAuthRepository
    # Where a run's output lines are captured: the worker appends them while
    # the task executes, the API's run stream reads them back. The two are
    # separate processes, so they only meet through a store both can reach —
    # in production the result-backend redis. No default: an API without one
    # cannot serve the run stream at all.
    task_output_store: ITaskOutputStore
    # Read side of msd's workspace: the Model Setup Data files earlier runs
    # produced. Needs no credentials — unlike the config-mgmt repository, it
    # reads this deployment's own artifacts, not a user's external data source
    # — so it is built once here rather than per session.
    msd_catalog: IModelSetupDataCatalog = field(
        default_factory=lambda: FilesystemModelSetupDataCatalog(workspace_root())
    )
    connections: Dict[str, Dict[SourceType, DataSourceConfig]] = field(default_factory=dict)

    def authenticate_user(self) -> AuthenticateUser:
        return AuthenticateUser(self.auth_repo)

    def open_token(self, token: str = None) -> str:
        """This session's slot in `connections`: the one it already holds, or
        a fresh empty one. Reusing the slot is what lets the two sources be
        connected in either order, and lets one be re-entered without
        disturbing the other."""
        if token in self.connections:
            return token
        token = secrets.token_urlsafe(16)
        self.connections[token] = {}
        return token

    def connect_config_mgmt_db(self, token: str, creds: dict) -> None:
        """creds: {"connection_address", "username", "password"}. Validated
        eagerly with a cheap query, so bad credentials are refused here
        rather than at run time."""
        data_source = self._build_data_source(SourceType.CONFIG_MGMT_DB, creds)
        self.config_repo_factory(data_source).list_projects()
        self.connections[token][SourceType.CONFIG_MGMT_DB] = data_source

    def connect_source_repo(self, token: str, creds: dict) -> None:
        """creds: {"connection_address", "username", "password"}. Source repo
        credentials can only really be validated by an actual clone, so
        they're stored unvalidated — a bad git credential surfaces later, at
        run time."""
        self.connections[token][SourceType.SOURCE_CODE_REPO] = self._build_data_source(
            SourceType.SOURCE_CODE_REPO, creds
        )

    def _build_data_source(self, source_type: SourceType, creds: dict) -> DataSourceConfig:
        default = self.defaults[source_type]
        return DataSourceConfig(
            source_type=source_type,
            source_name=default.source_name,
            access_method=default.access_method,
            connection_address=creds["connection_address"],
            user_info=f'{creds["username"]}:{creds["password"]}',
        )


def _build_source_repo(data_source: DataSourceConfig) -> ISourceCodeRepository:
    """The same construction vae's worker performs for a run — msd's analyzer
    patterns decide which Makefiles count as found, so they come from msd's own
    config rather than vae's."""
    return GitSourceCodeRepository.from_data_source_config(
        data_source, get_msd_config().analyzer.makefile_include_patterns
    )


def load_components() -> Components:
    config = get_config()
    defaults = {c.source_type: c for c in config.data_sources}
    missing = {SourceType.CONFIG_MGMT_DB, SourceType.SOURCE_CODE_REPO} - defaults.keys()
    if missing:
        names = ", ".join(sorted(s.value for s in missing))
        raise RuntimeError(f"missing data source(s) [{names}] in {DEFAULT_CONFIG_PATH}")
    return Components(
        defaults=defaults,
        config_repo_factory=MysqlConfigManagementRepository.from_data_source_config,
        source_repo_factory=_build_source_repo,
        msd_task_runner=CeleryTaskRunner(),
        auth_repo=LdapAuthRepository(),
        msd_catalog=FilesystemModelSetupDataCatalog(workspace_root()),
        task_output_store=RedisTaskOutputStore(config.worker.result_backend),
    )
