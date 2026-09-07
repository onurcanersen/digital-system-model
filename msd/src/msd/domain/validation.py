"""Mandatory-field validation over acquired/manual data (SRS DSM-MSD req 17-18)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict


@dataclass
class MandatoryFieldRule:
    """A single mandatory-field-presence rule (req 17).

    Attributes:
        field_name: The attribute name that must be present/non-empty.
        applies_to: The record type this rule applies to (e.g. "DataSourceConfig").
    """
    field_name: str
    applies_to: str


@dataclass
class ValidationError:
    """A single mandatory-field check failure (req 18)."""
    reason: str
    source_name: str
    source_type: str
    project_platform: str
    occurred_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reason": self.reason,
            "source_name": self.source_name,
            "source_type": self.source_type,
            "project_platform": self.project_platform,
            "occurred_at": self.occurred_at.isoformat(),
        }
