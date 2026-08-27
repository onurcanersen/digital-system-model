"""Pure unit test for mandatory_file_catalog.py's Makefile content-pattern
check (used by both git_source_code_repository.py and make_build_runner.py) — no
subprocess/git mocking needed (real git behavior stays manually verified,
not automated)."""

from adapters.source_code.mandatory_file_catalog import makefile_has_valid_include


def test_returns_true_when_pattern_present():
    content = "include include/Makefile_java.mk\n\n.PHONY: build\n"
    assert makefile_has_valid_include(content, ["include/Makefile_java.mk"]) is True


def test_returns_false_when_pattern_absent():
    content = ".PHONY: build\nbuild:\n\techo building\n"
    assert makefile_has_valid_include(content, ["include/Makefile_java.mk"]) is False


def test_ignores_pattern_inside_a_comment():
    content = "# include include/Makefile_java.mk\n.PHONY: build\n"
    assert makefile_has_valid_include(content, ["include/Makefile_java.mk"]) is False


def test_empty_pattern_list_never_matches():
    content = "include include/Makefile_java.mk\n"
    assert makefile_has_valid_include(content, []) is False


def test_matches_any_of_multiple_configured_patterns():
    content = "include include/Makefile_cpp.mk\n"
    patterns = ["include/Makefile_java.mk", "include/Makefile_cpp.mk"]
    assert makefile_has_valid_include(content, patterns) is True
