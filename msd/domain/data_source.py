"""Per-data-source configuration (SRS DSM-MSD req 2, 4)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict


class SourceType(Enum):
    """The external data-source categories DSM-MSD must access (req 2)."""
    CONFIG_MGMT_DB = "config_mgmt_db"
    SOURCE_CODE_REPO = "source_code_repo"


@dataclass
class DataSourceConfig:
    """User-definable connection info for one data source (req 4).

    Attributes:
        source_type: One of the SourceType categories.
        source_name: Human-readable name for this source.
        access_method: How it's reached (e.g. "mysql", "git").
        connection_address: Host/URL/path for the connection.
        user_info: Credentials or account identifier for the connection.
    """
    source_type: SourceType
    source_name: str
    access_method: str
    connection_address: str
    user_info: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_type": self.source_type.value,
            "source_name": self.source_name,
            "access_method": self.access_method,
            "connection_address": self.connection_address,
            "user_info": self.user_info,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "DataSourceConfig":
        return DataSourceConfig(
            source_type=SourceType(data["source_type"]),
            source_name=data["source_name"],
            access_method=data["access_method"],
            connection_address=data["connection_address"],
            user_info=data["user_info"],
        )
