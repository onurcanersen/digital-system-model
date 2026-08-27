"""TypeSupportParser — mock for topic schema/QoS data, aligned with the local
mock seed data (topic names taken from the seeded units' <unit>.xml manifests:
nav_app.xml, sensor_app.xml).

Called directly by adapters/json_model_setup_data_writer.py to enrich
the Model Setup Data graph (SRS DSM-MSD req 19); its formal port/use-case
abstraction is intentionally deferred.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Set

from model.model_setup_data import ModelSetupDataTopic

logger = logging.getLogger(__name__)


class TypeSupportParser:
    """Processes TypeSupport data (typically generated from IDLs)."""

    def __init__(self, selection_dir: Path):
        self.selection_dir = selection_dir
        # In a real implementation, generated TypeSupport files under
        # selection_dir (<workspace>/<project>/<platform>/<version>, holding
        # the cloned unit repos) would be scanned here. Currently returning
        # mock data aligned with the seeded units' topic manifests (see
        # module docstring).

    def get_topic_list(self) -> Set[ModelSetupDataTopic]:
        """Finds all topics with their QoS properties (SRS DSM-MSD req 19). Mock
        data using the topic names from the seeded units' <unit>.xml manifests
        (nav_position, sensor_data); size/QoS values are placeholder values."""
        logger.info("TypeSupportParser: retrieving topics from '%s'.", self.selection_dir)
        return {
            ModelSetupDataTopic(name="nav_position", size=6138, durability="PERSISTENT",
                                reliability="BEST_EFFORT", transport_priority="LOW"),
            ModelSetupDataTopic(name="sensor_data", size=1207, durability="TRANSIENT",
                                reliability="BEST_EFFORT", transport_priority="MEDIUM"),
        }
