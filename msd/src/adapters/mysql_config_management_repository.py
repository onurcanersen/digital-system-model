"""Real MySQL-backed adapter for IConfigManagementRepository.

Queries the mock configuration management database at dev/mysql
(schema: dev/mysql/init.sql — platform_pkg_version,
platform_current_atm_version, csu_csms_relation). There is no separate
surrogate id in that schema, so project_id/platform_id/version_id are the
natural project_name/platform_name/atm_version strings themselves.
"""

from __future__ import annotations

import logging
from typing import List, Optional

import pymysql
import pymysql.cursors

from model.system_hierarchy import SystemHierarchyRecord
from model.data_source import DataSourceConfig
from model.inventory import SoftwareUnitVersion
from model.project_context import PlatformRecord, ProjectRecord, VersionRecord
from ports.config_management_repository import ConfigManagementAccessError, IConfigManagementRepository

logger = logging.getLogger(__name__)


class MysqlConfigManagementRepository(IConfigManagementRepository):
    """Adapter querying the real (mock) MySQL configuration management database."""

    def __init__(self, host: str, port: int, user: str, password: str, database: str):
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._database = database

    @classmethod
    def from_data_source_config(cls, config: DataSourceConfig) -> "MysqlConfigManagementRepository":
        """Build a repository from a saved DataSourceConfig (req 4).

        Expects connection_address as "<host>:<port>/<database>" and
        user_info as "<user>:<password>" — matching dev/compose.yaml's
        defaults (dsm:dsm@localhost:3306/cmdb).
        """
        address, _, database = config.connection_address.partition("/")
        host, _, port = address.partition(":")
        user, _, password = config.user_info.partition(":")
        return cls(host=host, port=int(port or 3306), user=user, password=password, database=database)

    def _connect(self) -> pymysql.connections.Connection:
        try:
            return pymysql.connect(
                host=self._host,
                port=self._port,
                user=self._user,
                password=self._password,
                database=self._database,
                cursorclass=pymysql.cursors.DictCursor,
                connect_timeout=5,
            )
        except pymysql.MySQLError as exc:
            raise ConfigManagementAccessError(f"Cannot connect to config management database: {exc}") from exc

    def _fetchall(self, sql: str, args: tuple = ()) -> list:
        """Run a query, mapping any MySQL error to ConfigManagementAccessError (req 12)."""
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, args)
                    return cursor.fetchall()
        except pymysql.MySQLError as exc:
            raise ConfigManagementAccessError(f"Config management database query failed: {exc}") from exc

    def _fetchone(self, sql: str, args: tuple = ()):
        """Run a single-row query, mapping any MySQL error to ConfigManagementAccessError (req 12)."""
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, args)
                    return cursor.fetchone()
        except pymysql.MySQLError as exc:
            raise ConfigManagementAccessError(f"Config management database query failed: {exc}") from exc

    def list_projects(self) -> List[ProjectRecord]:
        rows = self._fetchall(
            "SELECT DISTINCT project_name FROM platform_pkg_version ORDER BY project_name"
        )
        return [ProjectRecord(project_id=row["project_name"], name=row["project_name"]) for row in rows]

    def list_platforms(self, project_id: str) -> List[PlatformRecord]:
        rows = self._fetchall(
            "SELECT DISTINCT platform_name FROM platform_pkg_version "
            "WHERE project_name = %s ORDER BY platform_name",
            (project_id,),
        )
        return [
            PlatformRecord(platform_id=row["platform_name"], project_id=project_id, name=row["platform_name"])
            for row in rows
        ]

    def list_versions(self, project_id: str, platform_id: str) -> List[VersionRecord]:
        version_rows = self._fetchall(
            "SELECT DISTINCT atm_version FROM platform_pkg_version "
            "WHERE project_name = %s AND platform_name = %s ORDER BY atm_version",
            (project_id, platform_id),
        )
        effective_rows = self._fetchall(
            "SELECT atm_version FROM platform_current_atm_version "
            "WHERE project_name = %s AND platform_name = %s",
            (project_id, platform_id),
        )
        effective_versions = {row["atm_version"] for row in effective_rows}
        return [
            VersionRecord(
                version_id=row["atm_version"],
                project_id=project_id,
                platform_id=platform_id,
                label=row["atm_version"],
                is_effective=row["atm_version"] in effective_versions,
            )
            for row in version_rows
        ]

    def list_unit_versions(self, project_id: str, platform_id: str, version_id: str) -> List[SoftwareUnitVersion]:
        rows = self._fetchall(
            "SELECT pkg_name, pkg_version FROM platform_pkg_version "
            "WHERE project_name = %s AND platform_name = %s AND atm_version = %s "
            "ORDER BY pkg_name",
            (project_id, platform_id, version_id),
        )
        return [SoftwareUnitVersion(unit_name=row["pkg_name"], version=row["pkg_version"]) for row in rows]

    def get_system_hierarchy(self, unit_name: str) -> Optional[SystemHierarchyRecord]:
        row = self._fetchone(
            "SELECT csu_name, csc_name, csci_name, css_name, csms_name, csu_description "
            "FROM csu_csms_relation WHERE csu_name = %s",
            (unit_name,),
        )
        if row is None:
            return None
        return SystemHierarchyRecord(**row)
