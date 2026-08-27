"""Tests for SystemRepoParser — the mock app-node/app-role/app-criticality
data that flows into the Model Setup Data graph via
json_model_setup_data_writer.py (SRS DSM-MSD req 3, 19)."""

from adapters.analysis.system_repo_parser import SystemRepoParser


def test_get_app_role_relation_returns_non_empty_role_lists(tmp_path):
    parser = SystemRepoParser(platform_name="mock-platform", project_name="mock-project", selection_dir=tmp_path)
    result = parser.get_app_role_relation()

    assert isinstance(result, dict)
    assert result, "mock data should not be empty"
    for app_name, roles in result.items():
        assert isinstance(app_name, str)
        assert isinstance(roles, list)
        assert all(isinstance(r, str) for r in roles)
        assert roles, f"{app_name}: role list must not be empty"


def test_get_app_node_relation_returns_pairs(tmp_path):
    parser = SystemRepoParser(platform_name="mock-platform", project_name="mock-project", selection_dir=tmp_path)
    result = parser.get_app_node_relation()

    assert result
    for app_name, node_name in result:
        assert isinstance(app_name, str)
        assert isinstance(node_name, str)


# The mock data must stay consistent with the seeded Gitea/mysql units,
# otherwise the graph builder's exact-name join silently drops the cloned
# apps from the graph.
SEED_UNITS = {"nav_app", "sensor_app", "common_lib"}


def test_get_app_node_relation_names_match_seeded_units(tmp_path):
    parser = SystemRepoParser(platform_name="mock-platform", project_name="mock-project", selection_dir=tmp_path)
    result = parser.get_app_node_relation()

    for app_name, _node_name in result:
        assert app_name in SEED_UNITS, (
            f"app-node mock references '{app_name}', which is not a seeded unit; "
            f"the graph join will drop its relations"
        )


def test_parser_stores_project_platform_and_selection_dir(tmp_path):
    parser = SystemRepoParser(platform_name="mock-platform", project_name="mock-project", selection_dir=tmp_path)

    assert parser.project_name == "mock-project"
    assert parser.platform_name == "mock-platform"
    assert parser.selection_dir == tmp_path
