"""System-hierarchy naming for software units (CSU -> CSC -> CSCI -> CSS -> CSMS),
obtained from the configuration management database (SRS DSM-MSD req 6-8) and
carried into the Model Setup Data graph (req 19) as each unit's
system-hierarchy attributes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class SystemHierarchyRecord:
    """One row of the csu_csms_relation table, keyed by software unit name."""
    csu_name: str
    csc_name: str
    csci_name: str
    css_name: str
    csms_name: str
    csu_description: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "csu_name": self.csu_name,
            "csc_name": self.csc_name,
            "csci_name": self.csci_name,
            "css_name": self.css_name,
            "csms_name": self.csms_name,
            "csu_description": self.csu_description,
        }
