"""Manual analysis strategy: XML topic parse + Java import scan
(SRS DSM-MSD req 13, 19 — topic/uses extraction from the acquired source).
CodeQL-based analysis is intentionally not supported.

Behavior:
  - The topic manifest is named "<folder_name>.xml" and searched for
    recursively under src/ (not a fixed name, not a direct path build).
  - Only imports ending in a configured suffix (e.g. "_lib") count as a
    "uses" dependency (via msd.ini's dependency_suffixes).
  - Topics matching a configured dummy-topic-name list are skipped (via
    msd.ini's dummy_topic_names).
  - The topic XML element name comes from msd.ini's custom_topic_name
    (default "topic").
Configurable values are read from msd.ini via adapters/config.py.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional, Set

from adapters.config import get_config
from model.topic_entry import TopicEntry
from ports.source_analyzer import ISourceAnalyzer

logger = logging.getLogger(__name__)

_IMPORT_PATTERN = re.compile(r"^\s*import\s+(?:static\s+)?([^;]+);", re.MULTILINE)
_COMMENT_PATTERN = re.compile(r"//.*?$|/\*.*?\*/", re.MULTILINE | re.DOTALL)


def _is_dummy_topic(topic_name: str) -> bool:
    dummy_names = {name.strip().lower() for name in get_config().analyzer.dummy_topic_names if name.strip()}
    return topic_name.strip().lower() in dummy_names


def _find_topic_manifest(folder_path: Path, folder_name: str) -> Optional[Path]:
    """Search recursively under folder_path/src for <folder_name>.xml,
    tolerating it being nested deeper than directly under src/."""
    src_path = folder_path / "src"
    if not src_path.exists():
        return None
    matches = sorted(src_path.glob(f"**/{folder_name}.xml"))
    return matches[0] if matches else None


def _parse_topic_xml(xml_path: Path, folder_name: str) -> List[TopicEntry]:
    entries: List[TopicEntry] = []
    try:
        root = ET.parse(xml_path).getroot()
        topic_tag = get_config().analyzer.custom_topic_name
        for topic in root.iter(topic_tag):
            name = topic.get("name")
            role = topic.get("role")
            if name and role:
                if _is_dummy_topic(name):
                    logger.debug("Skipping dummy topic in %s: %s", xml_path, name)
                    continue
                entries.append(TopicEntry(source_folder=folder_name, name=name, role=role.lower()))
    except ET.ParseError as exc:
        logger.error("Error parsing XML file %s: %s", xml_path, exc)
    return entries


def _parse_java_import_dependencies(project_path: Path) -> Set[str]:
    dependencies: Set[str] = set()
    if not project_path.exists():
        return dependencies

    config = get_config().analyzer
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

    def extract(self, folder_path: Path, folder_name: str) -> List[TopicEntry]:
        entries: List[TopicEntry] = []

        xml_path = _find_topic_manifest(folder_path, folder_name)
        if xml_path is not None:
            entries.extend(_parse_topic_xml(xml_path, folder_name))

        for dependency in _parse_java_import_dependencies(folder_path):
            if dependency != folder_name.strip():
                entries.append(TopicEntry(source_folder=folder_name, name=dependency, role="uses"))

        return entries
