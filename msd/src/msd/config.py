"""Loads config.ini — msd's single config file: the [analyzer] section that
tunes the source analysis adapters, and the [workspace] section that
configures the workflow's artifacts directory. Data-source connections
(config_mgmt_db, source_code_repo) are no longer msd's to own (SRS DSM-MSD
req 4) — msd.composition.load_components() now requires them to be supplied
by the caller (vae), which owns the sole config.ini for those. INI values
are parsed into frozen dataclasses; a missing file yields all built-in
defaults.
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.ini"

_ANALYZER_SECTION = "analyzer"
_WORKSPACE_SECTION = "workspace"


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
class Config:
    analyzer: AnalyzerConfig = field(default_factory=AnalyzerConfig)
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)


def load_config(path: Path) -> Config:
    """Parses the config file at `path`; a missing file yields all defaults."""
    if not path.exists():
        return Config()

    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path, encoding="utf-8")
    return Config(
        analyzer=_analyzer(parser),
        workspace=_workspace(parser),
    )


@lru_cache(maxsize=1)
def get_config() -> Config:
    return load_config(DEFAULT_CONFIG_PATH)


def _get_list(parser: configparser.ConfigParser, section: str, option: str) -> List[str]:
    if not parser.has_option(section, option):
        return []
    return [item.strip() for item in parser.get(section, option).split(",") if item.strip()]


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
