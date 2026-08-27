"""Acquisition and per-unit statuses shared across MSD use cases.

The string values are part of the API/UI contract (the status endpoint and the
UI's status styling), so the enums keep exactly those values."""

from enum import Enum


class AcquisitionStatus(Enum):
    """Outcome of a data-acquisition step (SRS DSM-MSD req 12, 15)."""
    OK = "OK"
    ERROR = "ERROR"
    MISSING_DATA = "MISSING_DATA"


class CloneStatus(Enum):
    """Outcome of cloning one unit's repository (SRS DSM-MSD req 13, 16)."""
    CLONED = "cloned"
    ALREADY_PRESENT = "already_present"
    ERROR = "error"


class GenerateUnitStatus(Enum):
    """Per-unit generate-stage status derived from the acquired-file records and
    the on-disk unit directories (SRS DSM-MSD req 14, 15, 16, 19)."""
    OK = "ok"
    MISSING_FILES = "missing_files"
    ERROR = "error"
    NOT_CLONED = "not_cloned"
