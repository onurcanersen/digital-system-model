"""Tests for make_build_runner.py — find_valid_makefile is pure filesystem logic
(no gmake needed); run_regenerate_code actually shells out to gmake, so it's
only exercised when gmake is available in the test environment
(environment-dependent tools are skipped, not mocked — no integration
tests). The makefile include patterns are passed explicitly (no msd.ini)."""

import pytest

from adapters.source_code.make_build_runner import (
    MakeBuildRunner,
    check_gmake_available,
    find_valid_makefile,
    run_regenerate_code,
)

PATTERNS = ["include/Makefile_java.mk"]


def test_find_valid_makefile_returns_none_when_absent(tmp_path):
    folder = tmp_path / "nav_app"
    folder.mkdir()

    assert find_valid_makefile(folder, PATTERNS) is None


def test_find_valid_makefile_returns_none_when_pattern_missing(tmp_path):
    folder = tmp_path / "nav_app"
    folder.mkdir()
    (folder / "Makefile").write_text(".PHONY: build\n", encoding="utf-8")

    assert find_valid_makefile(folder, PATTERNS) is None


def test_find_valid_makefile_finds_recursively_not_just_root(tmp_path):
    folder = tmp_path / "nav_app"
    (folder / "sub").mkdir(parents=True)
    (folder / "sub" / "Makefile").write_text("include include/Makefile_java.mk\n", encoding="utf-8")

    found = find_valid_makefile(folder, PATTERNS)

    assert found == folder / "sub" / "Makefile"


def test_find_valid_makefile_empty_patterns_never_match(tmp_path):
    folder = tmp_path / "nav_app"
    folder.mkdir()
    (folder / "Makefile").write_text("include include/Makefile_java.mk\n", encoding="utf-8")

    assert find_valid_makefile(folder, []) is None


def test_run_regenerate_code_reports_missing_gmake_gracefully(monkeypatch, tmp_path):
    monkeypatch.setattr("adapters.source_code.make_build_runner.subprocess.run", _raise_file_not_found)
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


# --- MakeBuildRunner (IBuildRunner adapter) ----------------------------------


def test_ensure_available_raises_when_gmake_missing(monkeypatch):
    monkeypatch.setattr("adapters.source_code.make_build_runner.check_gmake_available", lambda: False)

    with pytest.raises(RuntimeError, match="gmake is not available but build execution was requested"):
        MakeBuildRunner(PATTERNS).ensure_available()


def test_ensure_available_passes_when_gmake_present(monkeypatch):
    monkeypatch.setattr("adapters.source_code.make_build_runner.check_gmake_available", lambda: True)

    MakeBuildRunner(PATTERNS).ensure_available()


def test_regenerate_code_is_no_op_without_valid_makefile(monkeypatch, tmp_path):
    recorded = []
    monkeypatch.setattr("adapters.source_code.make_build_runner.run_regenerate_code",
                        lambda path, timeout=None: recorded.append(path) or (True, ""))
    unit_dir = tmp_path / "nav_app"
    unit_dir.mkdir()
    (unit_dir / "Makefile").write_text(".PHONY: build\n", encoding="utf-8")

    MakeBuildRunner(PATTERNS).regenerate_code(unit_dir)

    assert recorded == []


def test_regenerate_code_runs_when_valid_makefile_found(monkeypatch, tmp_path):
    recorded = []
    monkeypatch.setattr("adapters.source_code.make_build_runner.run_regenerate_code",
                        lambda path, timeout=None: recorded.append(path) or (True, ""))
    unit_dir = tmp_path / "nav_app"
    (unit_dir / "sub").mkdir(parents=True)
    makefile = unit_dir / "sub" / "Makefile"
    makefile.write_text("include include/Makefile_java.mk\n", encoding="utf-8")

    MakeBuildRunner(PATTERNS).regenerate_code(unit_dir)

    assert recorded == [makefile]
