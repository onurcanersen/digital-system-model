"""Tests for build_runner.py — find_valid_makefile is pure filesystem logic
(no gmake needed); run_regenerate_code actually shells out to gmake, so it's
only exercised when gmake is available in the test environment
(environment-dependent tools are skipped, not mocked — no integration
tests)."""

import pytest

from adapters.config import ENV_OVERRIDE_VAR, get_config
from adapters.source_code.build_runner import check_gmake_available, find_valid_makefile, run_regenerate_code


@pytest.fixture(autouse=True)
def _clear_config_cache():
    get_config.cache_clear()
    yield
    get_config.cache_clear()


def _write_config(tmp_path, monkeypatch, ini_body: str) -> None:
    config_path = tmp_path / "runtime.ini"
    config_path.write_text(ini_body, encoding="utf-8")
    monkeypatch.setenv(ENV_OVERRIDE_VAR, str(config_path))
    get_config.cache_clear()


def test_find_valid_makefile_returns_none_when_absent(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, "[analyzer]\nmakefile_include_patterns = include/Makefile_java.mk\n")
    folder = tmp_path / "nav_app"
    folder.mkdir()

    assert find_valid_makefile(folder) is None


def test_find_valid_makefile_returns_none_when_pattern_missing(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, "[analyzer]\nmakefile_include_patterns = include/Makefile_java.mk\n")
    folder = tmp_path / "nav_app"
    folder.mkdir()
    (folder / "Makefile").write_text(".PHONY: build\n", encoding="utf-8")

    assert find_valid_makefile(folder) is None


def test_find_valid_makefile_finds_recursively_not_just_root(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, "[analyzer]\nmakefile_include_patterns = include/Makefile_java.mk\n")
    folder = tmp_path / "nav_app"
    (folder / "sub").mkdir(parents=True)
    (folder / "sub" / "Makefile").write_text("include include/Makefile_java.mk\n", encoding="utf-8")

    found = find_valid_makefile(folder)

    assert found == folder / "sub" / "Makefile"


def test_run_regenerate_code_reports_missing_gmake_gracefully(monkeypatch, tmp_path):
    monkeypatch.setattr("adapters.source_code.build_runner.subprocess.run", _raise_file_not_found)
    makefile = tmp_path / "Makefile"
    makefile.write_text("", encoding="utf-8")

    success, message = run_regenerate_code(makefile)

    assert success is False
    assert "not found" in message


def _raise_file_not_found(*args, **kwargs):
    raise FileNotFoundError("gmake")


@pytest.mark.skipif(not check_gmake_available(), reason="gmake not installed in this environment")
def test_run_regenerate_code_succeeds_even_with_nonzero_exit_code(tmp_path):
    makefile = tmp_path / "Makefile"
    makefile.write_text("regenerate_code:\n\texit 1\n", encoding="utf-8")

    success, _ = run_regenerate_code(makefile)

    assert success is True
