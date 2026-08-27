"""Topic pub/sub/uses entries extracted from source units during analysis
(SRS DSM-MSD req 13, 19) — the raw feed for the Model Setup Data graph's
publishes_to/subscribes_to/uses relationships.

Project identification is deliberately kept out of these entries: per the
SRS, a "project" is a config-mgmt-DB entity (req 6) and is tracked in
model/project_context.py::ProjectRecord, not per extracted entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List


class TopicRole(Enum):
    """The pub/sub/pubsub roles a topic entry can carry (req 19)."""
    PUB = "pub"
    SUB = "sub"
    PUBSUB = "pubsub"


@dataclass
class TopicEntry:
    """A single topic pub/sub/uses entry extracted from a source unit (req 13, 19)."""
    source_folder: str
    name: str
    role: str


def expand_pubsub_entries(entries: List[TopicEntry]) -> List[TopicEntry]:
    """Expand pubsub entries into separate pub and sub entries, so the graph gains distinct publishes_to and subscribes_to relationships (req 19)."""
    expanded = []
    for entry in entries:
        if entry.role == TopicRole.PUBSUB.value:
            expanded.append(TopicEntry(source_folder=entry.source_folder, name=entry.name, role=TopicRole.PUB.value))
            expanded.append(TopicEntry(source_folder=entry.source_folder, name=entry.name, role=TopicRole.SUB.value))
        else:
            expanded.append(entry)
    return expanded
