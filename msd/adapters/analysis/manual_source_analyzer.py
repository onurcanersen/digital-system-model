"""Manual analysis strategy: XML topic parse + Java import scan
(SRS DSM-MSD req 13, 19 — topic/uses extraction from the acquired source).
CodeQL-based analysis is intentionally not supported.

Behavior:
  - The topic manifest is named "<folder_name>.xml" and searched for
    recursively under src/ (not a fixed name, not a direct path build).
  - Only imports ending in a configured suffix (e.g. "_lib") count as a
    "uses" dependency (via config.ini's dependency_suffixes).
  - Topics matching a configured dummy-topic-name list are skipped (via
    config.ini's dummy_topic_names).
  - The topic XML element name comes from config.ini's custom_topic_name
    (default "topic").
The settings (config.ini's [analyzer] section, as an AnalyzerConfig) are
injected at construction by the composition root.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional, Set

from config import AnalyzerConfig
from domain.extracted_topic import ExtractedTopic, TopicRole
from ports.source_analyzer import ISourceAnalyzer

logger = logging.getLogger(__name__)

_IMPORT_PATTERN = re.compile(r"^\s*import\s+(?:static\s+)?([^;]+);", re.MULTILINE)
_COMMENT_PATTERN = re.compile(r"//.*?$|/\*.*?\*/", re.MULTILINE | re.DOTALL)


def _is_dummy_topic(topic_name: str, dummy_topic_names: List[str]) -> bool:
    dummy_names = {name.strip().lower() for name in dummy_topic_names if name.strip()}
    return topic_name.strip().lower() in dummy_names


def _find_topic_manifest(folder_path: Path, folder_name: str) -> Optional[Path]:
    """Search recursively under folder_path/src for <folder_name>.xml,
    tolerating it being nested deeper than directly under src/."""
    src_path = folder_path / "src"
    if not src_path.exists():
        return None
    matches = sorted(src_path.glob(f"**/{folder_name}.xml"))
    return matches[0] if matches else None


def _parse_topic_xml(xml_path: Path, folder_name: str, config: AnalyzerConfig) -> List[ExtractedTopic]:
    entries: List[ExtractedTopic] = []
    try:
        root = ET.parse(xml_path).getroot()
        for topic in root.iter(config.custom_topic_name):
            name = topic.get("name")
            role_attr = topic.get("role")
            if name and role_attr:
                try:
                    role = TopicRole(role_attr.lower())
                except ValueError:
                    logger.debug("Skipping topic with unknown role in %s: %s (%s)", xml_path, name, role_attr)
                    continue
                if _is_dummy_topic(name, config.dummy_topic_names):
                    logger.debug("Skipping dummy topic in %s: %s", xml_path, name)
                    continue
                entries.append(ExtractedTopic(source_folder=folder_name, name=name, role=role))
    except ET.ParseError as exc:
        logger.error("Error parsing XML file %s: %s", xml_path, exc)
    return entries


def _parse_java_import_dependencies(project_path: Path, config: AnalyzerConfig) -> Set[str]:
    dependencies: Set[str] = set()
    if not project_path.exists():
        return dependencies

    domain_prefix = f"{config.import_domain_prefix}." if config.import_domain_prefix else None
    suffixes = tuple(config.dependency_suffixes)

    for java_file in project_path.rglob("*.java"):
        try:
            content = java_file.read_text(encoding="utf-8")
        except OSError as exc:
            logger.error("Error reading Java file %s: %s", java_file, exc)
            continue

        uncommented = _COMMENT_PATTERN.sub("", content)
        for import_target in _IMPORT_PATTERN.findall(uncommented):
            target = import_target.strip()
            if not domain_prefix or not target.startswith(domain_prefix):
                continue
            remainder = target[len(domain_prefix):]
            if not remainder:
                continue
            dependency_name = remainder.split(".", 1)[0].strip()
            if not dependency_name:
                continue
            if suffixes and not dependency_name.endswith(suffixes):
                continue
            dependencies.add(dependency_name)

    return dependencies


class ManualSourceAnalyzer(ISourceAnalyzer):
    """Extracts topics from a unit's <folder_name>.xml (found recursively under
    src/) and dependencies from its Java imports."""

    def __init__(self, config: AnalyzerConfig):
        self._config = config

    def extract(self, folder_path: Path, folder_name: str) -> List[ExtractedTopic]:
        entries: List[ExtractedTopic] = []

        xml_path = _find_topic_manifest(folder_path, folder_name)
        if xml_path is not None:
            entries.extend(_parse_topic_xml(xml_path, folder_name, self._config))

        for dependency in _parse_java_import_dependencies(folder_path, self._config):
            if dependency != folder_name.strip():
                entries.append(ExtractedTopic(source_folder=folder_name, name=dependency, role=TopicRole.USES))

        return entries
