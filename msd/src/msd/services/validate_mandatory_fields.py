"""Use case: mandatory-field-presence checks over acquired/manual data (SRS DSM-MSD req 17-18)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Tuple

from msd.domain.acquired_file import AcquiredFile
from msd.domain.data_source import DataSourceConfig
from msd.domain.project_context import ProjectContext
from msd.domain.extracted_topic import ExtractedTopic
from msd.domain.validation import MandatoryFieldRule, ValidationError


def _describe(record: Any) -> Tuple[str, str]:
    """Return (source_name, source_type) for a record, for error reporting (req 18)."""
    if isinstance(record, DataSourceConfig):
        return record.source_name, record.source_type.value
    if isinstance(record, AcquiredFile):
        return record.unit_name, "source_code_repo"
    if isinstance(record, ExtractedTopic):
        return record.source_folder, "source_code_repo"
    return type(record).__name__, "unknown"


class ValidateMandatoryFields:
    """Performs a mandatory-field-presence check for all source data received
    or manually entered (req 17), recording the error reason/source/type/
    project-platform/time for each failing datum (req 18)."""

    def __init__(self, rules: List[MandatoryFieldRule]):
        self._rules = rules

    def execute(self, records: List[Any], context: ProjectContext) -> List[ValidationError]:
        project_platform = f"{context.project.name}/{context.platform.name}"
        errors: List[ValidationError] = []

        for record in records:
            record_type = type(record).__name__
            for rule in self._rules:
                if rule.applies_to != record_type:
                    continue
                value = getattr(record, rule.field_name, None)
                if value in (None, ""):
                    source_name, source_type = _describe(record)
                    errors.append(ValidationError(
                        reason=f"'{rule.field_name}' is missing on {record_type}",
                        source_name=source_name,
                        source_type=source_type,
                        project_platform=project_platform,
                        occurred_at=datetime.now(),
                    ))

        return errors
