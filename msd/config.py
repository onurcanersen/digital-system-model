"""Loads config.ini — msd's single config file: the saved data-source
connections (SRS DSM-MSD req 4, one section per source type, named by that
type and carrying a source_name key), the [analyzer] section that tunes the
source analysis adapters, and the [workspace]/[api]/[worker] sections that
configure the rest of the app. INI values are parsed into frozen
dataclasses; a missing file yields all built-in defaults.
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List

from domain.data_source import DataSourceConfig, SourceType

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.ini"

_DATA_SOURCE_TYPES = {source_type.value for source_type in SourceType}

_ANALYZER_SECTION = "analyzer"
_WORKSPACE_SECTION = "workspace"
_API_SECTION = "api"
_WORKER_SECTION = "worker"


@dataclass(frozen=True)
class AnalyzerConfig:
    dummy_topic_names: List[str] = field(default_factory=list)
    import_domain_prefix: str = ""
    dependency_suffixes: List[str] = field(default_factory=list)
    makefile_include_patterns: List[str] = field(default_factory=list)
    custom_topic_name: str = "topic"
    run_build: bool = False


@dataclass(frozen=True)
class WorkspaceConfig:
    # Relative to the msd/ root unless absolute.
    path: str = "workspace"


@dataclass(frozen=True)
class ApiConfig:
    host: str = "127.0.0.1"
    port: int = 8080


@dataclass(frozen=True)
class WorkerConfig:
    broker_url: str = "redis://localhost:6379/0"
    result_backend: str = "redis://localhost:6379/1"


@dataclass(frozen=True)
class Config:
    data_sources: List[DataSourceConfig] = field(default_factory=list)
    analyzer: AnalyzerConfig = field(default_factory=AnalyzerConfig)
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
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
        analyzer=_analyzer(parser),
        workspace=_workspace(parser),
        api=_api(parser),
        worker=_worker(parser),
    )


@lru_cache(maxsize=1)
def get_config() -> Config:
    return load_config(DEFAULT_CONFIG_PATH)


def _get_list(parser: configparser.ConfigParser, section: str, option: str) -> List[str]:
    if not parser.has_option(section, option):
        return []
    return [item.strip() for item in parser.get(section, option).split(",") if item.strip()]


def _is_data_source_section(section: str) -> bool:
    return section in _DATA_SOURCE_TYPES


def _data_sources(parser: configparser.ConfigParser) -> List[DataSourceConfig]:
    configs = []
    for section in parser.sections():
        if not _is_data_source_section(section):
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


def _analyzer(parser: configparser.ConfigParser) -> AnalyzerConfig:
    if not parser.has_section(_ANALYZER_SECTION):
        return AnalyzerConfig()
    return AnalyzerConfig(
        dummy_topic_names=_get_list(parser, _ANALYZER_SECTION, "dummy_topic_names"),
        import_domain_prefix=parser.get(_ANALYZER_SECTION, "import_domain_prefix", fallback=""),
        dependency_suffixes=_get_list(parser, _ANALYZER_SECTION, "dependency_suffixes"),
        makefile_include_patterns=_get_list(parser, _ANALYZER_SECTION, "makefile_include_patterns"),
        custom_topic_name=parser.get(
            _ANALYZER_SECTION, "custom_topic_name", fallback=AnalyzerConfig().custom_topic_name
        ).strip()
        or AnalyzerConfig().custom_topic_name,
        run_build=parser.getboolean(_ANALYZER_SECTION, "run_build", fallback=False),
    )


def _workspace(parser: configparser.ConfigParser) -> WorkspaceConfig:
    path = parser.get(_WORKSPACE_SECTION, "path", fallback=WorkspaceConfig().path).strip()
    return WorkspaceConfig(path=path or WorkspaceConfig().path)


def _api(parser: configparser.ConfigParser) -> ApiConfig:
    return ApiConfig(
        host=parser.get(_API_SECTION, "host", fallback=ApiConfig().host),
        port=parser.getint(_API_SECTION, "port", fallback=ApiConfig().port),
    )


def _worker(parser: configparser.ConfigParser) -> WorkerConfig:
    return WorkerConfig(
        broker_url=parser.get(_WORKER_SECTION, "broker_url", fallback=WorkerConfig().broker_url),
        result_backend=parser.get(_WORKER_SECTION, "result_backend", fallback=WorkerConfig().result_backend),
    )
