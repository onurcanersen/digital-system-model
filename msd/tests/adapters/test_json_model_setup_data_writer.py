"""Tests for json_model_setup_data_writer.py's graph-building helpers
(SRS DSM-MSD req 19): QoS-derived topic frequency/criticality, topic node
creation, and application priority/hotstandby/role attributes."""

from adapters.json_model_setup_data_writer import (
    _APP_HOTSTANDBY_OPTIONS,
    _APP_PRIORITY_OPTIONS,
    _create_apps_libs_and_relations,
    _create_topics,
    _derive_topic_criticality,
    _derive_topic_frequency,
)
from domain.model_setup_data import ModelSetupDataTopic


# --- _derive_topic_frequency ------------------------------------------------

def test_frequency_max_for_reliable_urgent():
    assert _derive_topic_frequency("RELIABLE", "URGENT") == 200.0


def test_frequency_zero_score_yields_first_bin():
    assert _derive_topic_frequency("BEST_EFFORT", "URGENT") == 1.0
    assert _derive_topic_frequency("RELIABLE", "LOW") == 1.0


def test_frequency_reliable_high():
    assert _derive_topic_frequency("RELIABLE", "HIGH") == 100.0


def test_frequency_unknown_values_default_to_zero():
    assert _derive_topic_frequency("NOT_FOUND", "NOT_FOUND") == 1.0


# --- _derive_topic_criticality ----------------------------------------------

def test_criticality_minimal_for_all_lowest():
    assert _derive_topic_criticality("VOLATILE", "BEST_EFFORT", "LOW") == "minimal"


def test_criticality_critical_for_all_highest():
    assert _derive_topic_criticality("PERSISTENT", "RELIABLE", "URGENT") == "critical"


def test_criticality_medium_band():
    assert _derive_topic_criticality("PERSISTENT", "BEST_EFFORT", "LOW") == "medium"


def test_criticality_high_band():
    assert _derive_topic_criticality("PERSISTENT", "BEST_EFFORT", "HIGH") == "high"


def test_criticality_unknown_values_default_minimal():
    assert _derive_topic_criticality("NOT_FOUND", "NOT_FOUND", "NOT_FOUND") == "minimal"


# --- _create_topics integration ---------------------------------------------

def test_create_topics_adds_frequency_and_criticality():
    topic_set = {
        ModelSetupDataTopic(name="T-high", size=100, durability="PERSISTENT",
                             reliability="RELIABLE", transport_priority="URGENT"),
        ModelSetupDataTopic(name="T-low", size=100, durability="VOLATILE",
                             reliability="BEST_EFFORT", transport_priority="LOW"),
    }
    topics, _ = _create_topics(topic_set)
    by_name = {t["name"]: t for t in topics}

    assert by_name["T-high"]["frequency"] == 200.0
    assert by_name["T-high"]["criticality"] == "critical"
    assert by_name["T-low"]["frequency"] == 1.0
    assert by_name["T-low"]["criticality"] == "minimal"


# --- application priority / hotstandby ---------------------------------------

def _build_apps(app_role_map=None, app_criticality_map=None):
    app_node_rel = [("App-0", "Node-0"), ("App-1", "Node-1"), ("App-2", "Node-0")]
    apps, *_ = _create_apps_libs_and_relations(
        app_node_relations=app_node_rel,
        extracted_topics=[],
        topic_map={},
        app_role_map=app_role_map or {},
        app_criticality_map=app_criticality_map or {},
        unit_versions={},
        system_hierarchy_by_unit={},
    )
    return apps


def test_apps_have_priority_and_hotstandby_fields():
    for app in _build_apps():
        assert app["priority"] in _APP_PRIORITY_OPTIONS
        assert isinstance(app["hotstandby"], bool)
        assert app["hotstandby"] in _APP_HOTSTANDBY_OPTIONS


def test_app_priority_options_are_low_medium_high():
    assert set(_APP_PRIORITY_OPTIONS) == {"LOW", "MEDIUM", "HIGH"}


def test_app_attributes_are_reproducible_by_name():
    first = {a["name"]: (a["priority"], a["hotstandby"]) for a in _build_apps()}
    second = {a["name"]: (a["priority"], a["hotstandby"]) for a in _build_apps()}
    assert first == second


# --- application role (multi-role support) ----------------------------------

def _apps_with_roles(app_role_map):
    return {a["name"]: a["role"] for a in _build_apps(app_role_map=app_role_map)}


def test_app_role_defaults_to_not_found_list_when_missing():
    roles_by_app = _apps_with_roles({})
    for name, roles in roles_by_app.items():
        assert isinstance(roles, list), f"{name}: role must be a list"
        assert roles == ["NOT_FOUND"]


def test_app_role_preserves_single_role_as_list():
    roles_by_app = _apps_with_roles({"App-0": ["publisher"]})
    assert roles_by_app["App-0"] == ["publisher"]
    assert roles_by_app["App-1"] == ["NOT_FOUND"]


def test_app_role_preserves_multiple_roles():
    mapping = {
        "App-0": ["publisher", "monitor"],
        "App-2": ["publisher", "logger", "monitor"],
    }
    roles_by_app = _apps_with_roles(mapping)
    assert roles_by_app["App-0"] == ["publisher", "monitor"]
    assert roles_by_app["App-2"] == ["publisher", "logger", "monitor"]
    assert roles_by_app["App-1"] == ["NOT_FOUND"]


def test_app_role_is_copied_not_aliased():
    shared = ["publisher", "monitor"]
    mapping = {"App-0": shared}
    roles_by_app = _apps_with_roles(mapping)
    roles_by_app["App-0"].append("mutated")
    assert shared == ["publisher", "monitor"]
