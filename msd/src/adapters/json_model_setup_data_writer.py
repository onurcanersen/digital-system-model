"""Builds the node-relationship-shaped graph payload and writes ModelSetupData
to JSON (SRS DSM-MSD req 19).

The topic/QoS data already arrives DDS-formatted (both the mock
TypeSupportParser and the real generated TypeSupport files use DDS strings
directly), so there is no custom-to-DDS QoS conversion layer, and topic
pub/sub/uses entries are consumed in-memory — AnalyzeSourceUnitsUseCase
already produces them as TopicEntry objects, so no CSV round-trip is needed.

Calls system_repo_parser.py and type_support_parser.py directly for
enrichment — neither maps to one of the four SRS-named external-source ports
(req 2), so there's no port between this writer and those two mocks.
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from adapters.analysis.system_repo_parser import SystemRepoParser
from adapters.analysis.type_support_parser import TypeSupportParser
from model.system_hierarchy import SystemHierarchyRecord
from model.inventory import SoftwareUnitVersionInventory
from model.model_setup_data import ModelSetupData, ModelSetupDataTopic
from model.topic_entry import TopicEntry
from ports.config_management_repository import IConfigManagementRepository

logger = logging.getLogger(__name__)

# QoS-derived topic attributes (frequency/criticality bins and score
# weights), kept local to msd.
TOPIC_FREQUENCY_HZ: List[float] = [
    1.0, 1.0, 5.0, 10.0, 10.0, 20.0, 20.0, 50.0,
    50.0, 100.0, 100.0, 150.0, 150.0, 200.0, 200.0, 200.0,
]
CRITICALITY_THRESHOLDS: List[Tuple[float, str]] = [
    (0.00, "minimal"), (0.19, "low"), (0.43, "medium"), (0.64, "high"), (1.00, "critical"),
]
_RELIABILITY_SCORES: Dict[str, float] = {"BEST_EFFORT": 0.0, "RELIABLE": 1.0}
_DURABILITY_SCORES: Dict[str, float] = {
    "VOLATILE": 0.0, "TRANSIENT_LOCAL": 0.5, "TRANSIENT": 0.6, "PERSISTENT": 1.0,
}
_PRIORITY_SCORES: Dict[str, float] = {"LOW": 0.0, "MEDIUM": 0.33, "HIGH": 0.66, "URGENT": 1.0}
_W_RELIABILITY, _W_DURABILITY, _W_PRIORITY = 0.30, 0.40, 0.30

_APP_PRIORITY_OPTIONS: List[str] = ["LOW", "MEDIUM", "HIGH"]
_APP_HOTSTANDBY_OPTIONS: List[bool] = [False, True]

_DEFAULT_HIERARCHY = {"csc_name": "NOT_FOUND", "csci_name": "NOT_FOUND", "css_name": "NOT_FOUND", "csms_name": "NOT_FOUND", "csu_description": "NOT_FOUND"}


def _derive_topic_frequency(reliability: str, transport_priority: str) -> float:
    r = _RELIABILITY_SCORES.get(reliability, 0.0)
    p = _PRIORITY_SCORES.get(transport_priority, 0.0)
    bin_idx = int(r * p * len(TOPIC_FREQUENCY_HZ))
    bin_idx = max(0, min(bin_idx, len(TOPIC_FREQUENCY_HZ) - 1))
    return float(TOPIC_FREQUENCY_HZ[bin_idx])


def _derive_topic_criticality(durability: str, reliability: str, transport_priority: str) -> str:
    score = (
        _W_RELIABILITY * _RELIABILITY_SCORES.get(reliability, 0.0)
        + _W_DURABILITY * _DURABILITY_SCORES.get(durability, 0.0)
        + _W_PRIORITY * _PRIORITY_SCORES.get(transport_priority, 0.0)
    )
    for threshold, label in CRITICALITY_THRESHOLDS:
        if score <= threshold:
            return label
    return "critical"


def _hierarchy_dict(record: Optional[SystemHierarchyRecord]) -> Dict[str, str]:
    if record is None:
        return dict(_DEFAULT_HIERARCHY)
    return {
        "csc_name": record.csc_name,
        "csci_name": record.csci_name,
        "css_name": record.css_name,
        "csms_name": record.csms_name,
        "csu_description": record.csu_description,
    }


def _create_nodes(app_node_relations: List[Tuple[str, str]]) -> Tuple[List[Dict[str, str]], Dict[str, str]]:
    node_names = sorted({name for _, name in app_node_relations if name and name != "NOT_FOUND"})
    node_map = {name: f"N{i}" for i, name in enumerate(node_names)}
    nodes = [{"id": node_map[name], "name": name} for name in node_names]
    return nodes, node_map


def _create_topics(topic_set: Set[ModelSetupDataTopic]) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    topics: List[Dict[str, Any]] = []
    topic_map: Dict[str, str] = {}
    for i, topic in enumerate(sorted(topic_set, key=lambda t: t.name)):
        topic_id = f"T{i}"
        qos_dur = topic.durability or "NOT_FOUND"
        qos_rel = topic.reliability or "NOT_FOUND"
        qos_pri = topic.transport_priority or "NOT_FOUND"
        topics.append({
            "id": topic_id,
            "name": topic.name,
            "size": topic.size if topic.size is not None else -1,
            "qos": {"durability": qos_dur, "reliability": qos_rel, "transport_priority": qos_pri},
            "frequency": _derive_topic_frequency(qos_rel, qos_pri),
            "criticality": _derive_topic_criticality(qos_dur, qos_rel, qos_pri),
        })
        topic_map[topic.name] = topic_id
    return topics, topic_map


def _create_apps_libs_and_relations(
    app_node_relations: List[Tuple[str, str]],
    topic_entries: List[TopicEntry],
    topic_map: Dict[str, str],
    app_role_map: Dict[str, List[str]],
    app_criticality_map: Dict[str, bool],
    unit_versions: Dict[str, str],
    system_hierarchy_by_unit: Dict[str, Optional[SystemHierarchyRecord]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, str]], List[Dict[str, str]], List[Dict[str, str]]]:
    app_names: Set[str] = {app for app, _ in app_node_relations}
    lib_names: Set[str] = set()

    for entry in topic_entries:
        if entry.role == "uses" and entry.source_folder in app_names and entry.name not in app_names:
            lib_names.add(entry.name)

    sorted_app_names = sorted(app_names)
    app_map = {name: f"A{i}" for i, name in enumerate(sorted_app_names)}
    sorted_lib_names = sorted(lib_names)
    lib_map = {name: f"L{i}" for i, name in enumerate(sorted_lib_names)}

    libs = [
        {
            "id": lib_map[name],
            "name": name,
            "version": unit_versions.get(name, "NOT_FOUND"),
            "system_hierarchy": _hierarchy_dict(system_hierarchy_by_unit.get(name)),
        }
        for name in sorted_lib_names
    ]

    publishes_to: List[Dict[str, str]] = []
    subscribes_to: List[Dict[str, str]] = []
    uses: List[Dict[str, str]] = []

    for entry in topic_entries:
        source_id = app_map.get(entry.source_folder) or lib_map.get(entry.source_folder)
        if not source_id:
            continue
        if entry.role in ("pub", "sub") and entry.name in topic_map:
            relation = {"from": source_id, "to": topic_map[entry.name]}
            (publishes_to if entry.role == "pub" else subscribes_to).append(relation)
        elif entry.role == "uses":
            target_id = lib_map.get(entry.name) or app_map.get(entry.name)
            if target_id:
                uses.append({"from": source_id, "to": target_id})

    applications: List[Dict[str, Any]] = []
    for name in sorted_app_names:
        criticality_value = bool(app_criticality_map.get(name, False))
        app_rng = random.Random(name)
        applications.append({
            "id": app_map[name],
            "name": name,
            "version": unit_versions.get(name, "NOT_FOUND"),
            "role": list(app_role_map.get(name, ["NOT_FOUND"])),
            "criticality": criticality_value,
            "priority": app_rng.choice(_APP_PRIORITY_OPTIONS),
            "hotstandby": app_rng.choice(_APP_HOTSTANDBY_OPTIONS),
            "system_hierarchy": _hierarchy_dict(system_hierarchy_by_unit.get(name)),
        })

    return applications, libs, publishes_to, subscribes_to, uses


class JsonModelSetupDataWriter:
    """Adapter implementing IModelSetupDataWriter, plus the graph-building
    step GenerateModelSetupDataUseCase calls before constructing ModelSetupData.

    `write` persists the graph payload only (nodes/topics/applications/
    libraries/relationships) — the surrounding context/inventory/
    acquisition data stays on the in-memory ModelSetupData and on the
    caller's response, not on disk."""

    def __init__(self, platform_name: str, project_name: str, version: str, selection_dir: Path):
        self._platform_name = platform_name
        self._project_name = project_name
        self._version = version
        self._selection_dir = selection_dir

    def build_graph(
        self,
        inventory: SoftwareUnitVersionInventory,
        topic_entries: List[TopicEntry],
        config_repo: IConfigManagementRepository,
    ) -> Dict[str, Any]:
        """Build the nodes/topics/applications/libraries/relationships payload."""
        system_repo = SystemRepoParser(self._selection_dir, self._project_name, self._platform_name)
        type_support = TypeSupportParser(self._selection_dir)

        app_node_relations = system_repo.get_app_node_relation()
        app_role_map = system_repo.get_app_role_relation()
        app_criticality_map = system_repo.get_app_criticality_relation()
        topic_set = type_support.get_topic_list()

        unit_versions = {u.unit_name: u.version for u in inventory.units}
        system_hierarchy_by_unit = {
            unit.unit_name: config_repo.get_system_hierarchy(unit.unit_name) for unit in inventory.units
        }

        nodes, _node_map = _create_nodes(app_node_relations)
        topics, topic_map = _create_topics(topic_set)
        applications, libs, publishes_to, subscribes_to, uses = _create_apps_libs_and_relations(
            app_node_relations, topic_entries, topic_map, app_role_map,
            app_criticality_map, unit_versions, system_hierarchy_by_unit,
        )

        return {
            "metadata": {
                "scale": {"apps": len(applications), "topics": len(topics), "nodes": len(nodes), "libraries": len(libs)},
            },
            "nodes": nodes,
            "topics": topics,
            "applications": applications,
            "libraries": libs,
            "relationships": {
                "runs_on": [
                    {"from": app, "to": node} for app, node in app_node_relations
                    if node and node != "NOT_FOUND"
                ],
                "publishes_to": publishes_to,
                "subscribes_to": subscribes_to,
                "uses": uses,
            },
        }

    def write(self, data: ModelSetupData, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(data.graph, indent=2), encoding="utf-8")
        logger.info("Model Setup Data graph written to %s", output_path)
        return output_path
