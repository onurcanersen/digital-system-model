"""Acquisition status shared across MSD use cases."""

from enum import Enum


class AcquisitionStatus(Enum):
    """Outcome of a data-acquisition step (SRS DSM-MSD req 12, 15)."""
    OK = "OK"
    ERROR = "ERROR"
    MISSING_DATA = "MISSING_DATA"
