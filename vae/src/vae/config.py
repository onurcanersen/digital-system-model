"""Loads vae's own config.ini: a config_mgmt_db data source (reusing msd's
DataSourceConfig/SourceType domain types, since that's a shared domain
concept) plus vae's own [api] and [worker] sections — vae is the sole
serving layer (Flask API + Celery worker); msd is a library with no config
of its own for either."""

from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List

from msd.domain.data_source import DataSourceConfig, SourceType

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.ini"

_DATA_SOURCE_TYPES = {source_type.value for source_type in SourceType}
_API_SECTION = "api"
_WORKER_SECTION = "worker"


@dataclass(frozen=True)
class ApiConfig:
    host: str = "127.0.0.1"
    port: int = 8080
    secret_key: str = "dev-insecure-change-me"


@dataclass(frozen=True)
class WorkerConfig:
    broker_url: str = "redis://localhost:6379/0"
    result_backend: str = "redis://localhost:6379/1"


@dataclass(frozen=True)
class Config:
    data_sources: List[DataSourceConfig] = field(default_factory=list)
    api: ApiConfig = field(default_factory=ApiConfig)
    worker: WorkerConfig = field(default_factory=WorkerConfig)


def load_config(path: Path) -> Config:
    """Parses the config file at `path`; a missing file yields all defaults."""
    if not path.exists():
        return Config()

    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path, encoding="utf-8")
    return Config(
        data_sources=_data_sources(parser),
        api=_api(parser),
        worker=_worker(parser),
    )


@lru_cache
def get_config() -> Config:
    return load_config(DEFAULT_CONFIG_PATH)


def _data_sources(parser: configparser.ConfigParser) -> List[DataSourceConfig]:
    configs = []
    for section in parser.sections():
        if section not in _DATA_SOURCE_TYPES:
            continue
        configs.append(
            DataSourceConfig.from_dict(
                {
                    "source_type": section,
                    "source_name": parser.get(section, "source_name", fallback=""),
                    "access_method": parser.get(section, "access_method", fallback=""),
                    "connection_address": parser.get(section, "connection_address", fallback=""),
                    "user_info": parser.get(section, "user_info", fallback=""),
                }
            )
        )
    return configs


def _api(parser: configparser.ConfigParser) -> ApiConfig:
    return ApiConfig(
        host=parser.get(_API_SECTION, "host", fallback=ApiConfig().host),
        port=parser.getint(_API_SECTION, "port", fallback=ApiConfig().port),
        secret_key=parser.get(_API_SECTION, "secret_key", fallback=ApiConfig().secret_key),
    )


def _worker(parser: configparser.ConfigParser) -> WorkerConfig:
    return WorkerConfig(
        broker_url=parser.get(_WORKER_SECTION, "broker_url", fallback=WorkerConfig().broker_url),
        result_backend=parser.get(_WORKER_SECTION, "result_backend", fallback=WorkerConfig().result_backend),
    )
