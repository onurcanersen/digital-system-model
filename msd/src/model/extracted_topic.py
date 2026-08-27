"""ExtractedTopic — topic pub/sub/uses entries extracted from software units
during analysis (SRS DSM-MSD req 13, 19) — the raw feed for the Model Setup
Data graph's publishes_to/subscribes_to/uses relationships.

Project identification is deliberately kept out of these entries: per the
SRS, a "project" is a config-mgmt-DB entity (req 6) and is tracked in
model/project_context.py::ProjectRecord, not per extracted topic.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List


class TopicRole(Enum):
    """The pub/sub/pubsub/uses roles a topic entry can carry (req 19)."""
    PUB = "pub"
    SUB = "sub"
    PUBSUB = "pubsub"
    USES = "uses"


@dataclass
class ExtractedTopic:
    """A single topic pub/sub/uses entry extracted from a software unit (req 13, 19)."""
    source_folder: str
    name: str
    role: TopicRole


def expand_pubsub_entries(entries: List[ExtractedTopic]) -> List[ExtractedTopic]:
    """Expand pubsub entries into separate pub and sub entries, so the graph gains distinct publishes_to and subscribes_to relationships (req 19)."""
    expanded = []
    for entry in entries:
        if entry.role == TopicRole.PUBSUB:
            expanded.append(ExtractedTopic(source_folder=entry.source_folder, name=entry.name, role=TopicRole.PUB))
            expanded.append(ExtractedTopic(source_folder=entry.source_folder, name=entry.name, role=TopicRole.SUB))
        else:
            expanded.append(entry)
    return expanded
