"""Loads msd.ini — msd's single config file (SRS DSM-MSD req 4: the saved
data-source connections, one section per source named "<source_type>.<source_name>",
plus the [analyzer] section that tunes the source analysis adapters). INI
values are parsed into frozen dataclasses; the MSD_CONFIG env var
overrides the file path. Placed under adapters/ (not a new top-level package)
since reading a file from disk is an adapter-level concern.
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List

from model.data_source import DataSourceConfig, SourceType

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "msd.ini"
ENV_OVERRIDE_VAR = "MSD_CONFIG"
_SECTION = "analyzer"

_DATA_SOURCE_TYPES = {source_type.value for source_type in SourceType}


@dataclass(frozen=True)
class AnalyzerConfig:
    dummy_topic_names: List[str] = field(default_factory=list)
    import_domain_prefix: str = ""
    dependency_suffixes: List[str] = field(default_factory=list)
    makefile_include_patterns: List[str] = field(default_factory=list)
    custom_topic_name: str = "topic"
    run_build: bool = False


@dataclass(frozen=True)
class Config:
    analyzer: AnalyzerConfig = field(default_factory=AnalyzerConfig)
    data_sources: List[DataSourceConfig] = field(default_factory=list)


def config_path() -> Path:
    override = os.environ.get(ENV_OVERRIDE_VAR)
    return Path(override) if override else DEFAULT_CONFIG_PATH


def _get_list(parser: configparser.ConfigParser, option: str) -> List[str]:
    if not parser.has_option(_SECTION, option):
        return []
    return [item.strip() for item in parser.get(_SECTION, option).split(",") if item.strip()]


def _is_data_source_section(section: str) -> bool:
    source_type, sep, _ = section.partition(".")
    return bool(sep) and source_type in _DATA_SOURCE_TYPES


def _data_sources(parser: configparser.ConfigParser) -> List[DataSourceConfig]:
    configs = []
    for section in parser.sections():
        if not _is_data_source_section(section):
            continue
        source_type, _, source_name = section.partition(".")
        configs.append(
            DataSourceConfig.from_dict(
                {
                    "source_type": source_type,
                    "source_name": source_name,
                    "access_method": parser.get(section, "access_method", fallback=""),
                    "connection_address": parser.get(section, "connection_address", fallback=""),
                    "user_info": parser.get(section, "user_info", fallback=""),
                }
            )
        )
    return configs


def _analyzer(parser: configparser.ConfigParser) -> AnalyzerConfig:
    if not parser.has_section(_SECTION):
        return AnalyzerConfig()
    return AnalyzerConfig(
        dummy_topic_names=_get_list(parser, "dummy_topic_names"),
        import_domain_prefix=parser.get(_SECTION, "import_domain_prefix", fallback=""),
        dependency_suffixes=_get_list(parser, "dependency_suffixes"),
        makefile_include_patterns=_get_list(parser, "makefile_include_patterns"),
        custom_topic_name=parser.get(_SECTION, "custom_topic_name", fallback="topic").strip() or "topic",
        run_build=parser.getboolean(_SECTION, "run_build", fallback=False),
    )


@lru_cache(maxsize=1)
def get_config() -> Config:
    path = config_path()
    if not path.exists():
        return Config()

    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path, encoding="utf-8")
    return Config(analyzer=_analyzer(parser), data_sources=_data_sources(parser))
