"""SystemRepoParser — mock for app-node/app-role/app-criticality data, aligned
with the local mock seed data (dev/gitea repos + dev/mysql: project
'skywatch', platform 'nftw', version '1.0.0', units nav_app,
sensor_app, common_lib).

This is the app-node placement piece of what the SRS calls "network
topology" (req 3) — its formal port/use-case abstraction is intentionally
deferred, but the underlying data still flows into ModelSetupData: it is
called directly by adapters/json_model_setup_data_writer.py.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


class SystemRepoParser:
    """Processes System Application Repository data."""

    def __init__(self, selection_dir: Path, project_name: str, platform_name: str):
        self.selection_dir = selection_dir
        self.project_name = project_name
        self.platform_name = platform_name
        # In a real implementation, project- and platform-specific
        # SYSTEM_REPO files/API would be read here, e.g. under
        # selection_dir. Currently returning mock data aligned with the
        # local Gitea/mysql seed (see module docstring).

    def get_app_node_relation(self) -> List[Tuple[str, str]]:
        """Returns which nodes applications run on (SRS DSM-MSD req 3). Mock data
        mirroring the seeded units (nav_app, sensor_app). common_lib is a library,
        not an application placed on a node, so it is intentionally absent here
        (it enters the graph via 'uses' edges instead)."""
        logger.info("SystemRepoParser: retrieving app-node relationships for project '%s' / platform '%s' / selection dir '%s'.", self.project_name, self.platform_name, self.selection_dir)
        return [
            # Node assignment is arbitrary mock data.
            ("nav_app", "Node-0"),
            ("sensor_app", "Node-1"),
        ]

    def get_app_role_relation(self) -> Dict[str, List[str]]:
        """Returns application role information (SRS DSM-MSD req 3). Mock data
        mirroring each unit's topic manifest (nav_app: pub nav_position + sub
        sensor_data; sensor_app: pub sensor_data)."""
        logger.info("SystemRepoParser: retrieving app-role relationships for project '%s' / platform '%s' / selection dir '%s'.", self.project_name, self.platform_name, self.selection_dir)
        return {
            "nav_app": ["publisher", "subscriber"],
            "sensor_app": ["publisher"],
        }

    def get_app_criticality_relation(self) -> Dict[str, bool]:
        """Returns application criticality information. Empty in the current mock data (SRS DSM-MSD req 3)."""
        logger.info("SystemRepoParser: retrieving app-criticality relationships for project '%s' / platform '%s' / selection dir '%s'.", self.project_name, self.platform_name, self.selection_dir)
        return {}
