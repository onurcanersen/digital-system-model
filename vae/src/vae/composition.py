"""Composition root for VAE: builds VAE's own config-mgmt repository factory
(by reusing msd's adapter directly, SRS DSM-VAE req 2, 4-5), VAE's own
Celery-backed task runner (task_runner.py), which triggers/tracks vae's
own run_msd_workflow task — msd itself has no API/worker/task of its own
(see msd.composition.load_components, which that task calls into) — and
VAE's own auth repository (SRS DSM-VAE req 3).

VAE owns the sole config.ini for data-source connection *addresses*
(config_mgmt_db, source_code_repo — msd no longer keeps its own copy).
Credentials are never defaulted from that file: they're supplied by the
user via two sequential post-login "connect" steps, one card per data
source (api.py's /api/data-sources/connect/config-mgmt-db and
/connect/source-code-repo), and held only in-memory, per session, here in
`Components.connections`.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Callable, Dict

from msd.adapters.mysql_config_management_repository import MysqlConfigManagementRepository
from msd.domain.data_source import DataSourceConfig, SourceType
from msd.ports.config_management_repository import IConfigManagementRepository

from vae.adapters.in_memory_ldap_auth_repository import InMemoryLdapAuthRepository
from vae.adapters.in_memory_task_output_store import InMemoryTaskOutputStore
from vae.adapters.redis_task_output_store import RedisTaskOutputStore
from vae.config import DEFAULT_CONFIG_PATH, get_config
from vae.ports.auth_repository import IAuthRepository
from vae.ports.task_output_store import ITaskOutputStore
from vae.services.authenticate_user import AuthenticateUser
from vae.task_runner import CeleryTaskRunner, ITaskRunner


@dataclass
class Components:
    defaults: Dict[SourceType, DataSourceConfig]
    config_repo_factory: Callable[[DataSourceConfig], IConfigManagementRepository]
    msd_task_runner: ITaskRunner
    auth_repo: IAuthRepository
    task_output_store: ITaskOutputStore = field(default_factory=InMemoryTaskOutputStore)
    connections: Dict[str, Dict[SourceType, DataSourceConfig]] = field(default_factory=dict)

    def authenticate_user(self) -> AuthenticateUser:
        return AuthenticateUser(self.auth_repo)

    def connect_config_mgmt_db(self, creds: dict) -> str:
        """creds: {"connection_address", "username", "password"}. Validates
        eagerly (a cheap query) and starts a fresh connection — any
        source_code_repo connected under a previous token for this session
        is dropped, since the wizard always starts here."""
        data_source = self._build_data_source(SourceType.CONFIG_MGMT_DB, creds)
        self.config_repo_factory(data_source).list_projects()
        token = secrets.token_urlsafe(16)
        self.connections[token] = {SourceType.CONFIG_MGMT_DB: data_source}
        return token

    def connect_source_repo(self, token: str, creds: dict) -> None:
        """creds: {"connection_address", "username", "password"}. Adds
        source_code_repo to the connection started by connect_config_mgmt_db.
        Source repo credentials can only really be validated by an actual
        clone, so they're stored unvalidated — a bad git credential surfaces
        later, at run time."""
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
        msd_task_runner=CeleryTaskRunner(),
        auth_repo=InMemoryLdapAuthRepository(),
        task_output_store=RedisTaskOutputStore(config.worker.result_backend),
    )
