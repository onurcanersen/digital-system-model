"""Tests for MysqlConfigManagementRepository error mapping (SRS DSM-MSD req 12):
both connection and query-level MySQL errors must surface as
ConfigManagementAccessError, never as raw pymysql exceptions."""

import pymysql

from msd.adapters.mysql_config_management_repository import MysqlConfigManagementRepository
from msd.ports.config_management_repository import ConfigManagementAccessError


def _repo() -> MysqlConfigManagementRepository:
    return MysqlConfigManagementRepository(
        host="localhost", port=3306, user="dsm", password="dsm", database="cmdb"
    )


def test_connection_error_maps_to_config_management_access_error(monkeypatch):
    def boom(**kwargs):
        raise pymysql.err.OperationalError(2003, "Can't connect to MySQL server")

    monkeypatch.setattr(pymysql, "connect", boom)

    try:
        _repo().list_projects()
        assert False, "expected ConfigManagementAccessError"
    except ConfigManagementAccessError as exc:
        assert "Cannot connect" in str(exc)


def test_query_error_maps_to_config_management_access_error(monkeypatch):
    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, args=None):
            raise pymysql.err.ProgrammingError(1146, "Table 'cmdb.csu_csms_relation' doesn't exist")

        def fetchall(self):
            return []

        def fetchone(self):
            return None

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return _Cursor()

    monkeypatch.setattr(pymysql, "connect", lambda **kwargs: _Conn())
    repo = _repo()

    for call in (lambda: repo.list_projects(), lambda: repo.get_system_hierarchy("nav_app")):
        try:
            call()
            assert False, "expected ConfigManagementAccessError"
        except ConfigManagementAccessError as exc:
            assert "query failed" in str(exc)
