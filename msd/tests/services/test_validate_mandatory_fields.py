from datetime import datetime

from msd.domain.acquired_file import AcquiredFile
from msd.domain.data_source import DataSourceConfig, SourceType
from msd.domain.project_context import ProjectContext, PlatformRecord, ProjectRecord, VersionRecord
from msd.domain.extracted_topic import ExtractedTopic, TopicRole
from msd.domain.validation import MandatoryFieldRule
from msd.services.validate_mandatory_fields import ValidateMandatoryFields


def _context() -> ProjectContext:
    return ProjectContext(
        project=ProjectRecord("proj-1", "skywatch"),
        platform=PlatformRecord("plat-1", "proj-1", "nftw"),
        version=VersionRecord("1.0.0", "proj-1", "plat-1", "1.0.0", is_effective=True),
    )


def test_valid_records_produce_no_errors():
    rules = [MandatoryFieldRule("file_name", "AcquiredFile")]
    record = AcquiredFile("nav_app", "Makefile", "Makefile", "1.0.0", datetime.now())

    errors = ValidateMandatoryFields(rules).execute([record], _context())

    assert errors == []


def test_missing_field_produces_validation_error_with_required_shape():
    rules = [MandatoryFieldRule("name", "ExtractedTopic")]
    record = ExtractedTopic(source_folder="nav_app", name="", role=TopicRole.PUB)

    errors = ValidateMandatoryFields(rules).execute([record], _context())

    assert len(errors) == 1
    error = errors[0]
    assert "name" in error.reason
    assert error.source_name == "nav_app"
    assert error.source_type == "source_code_repo"
    assert error.project_platform == "skywatch/nftw"
    assert error.occurred_at is not None


def test_rule_only_applies_to_its_record_type():
    rules = [MandatoryFieldRule("user_info", "DataSourceConfig")]
    extracted_topic = ExtractedTopic(source_folder="nav_app", name="", role=TopicRole.PUB)

    errors = ValidateMandatoryFields(rules).execute([extracted_topic], _context())

    assert errors == []


def test_missing_field_on_data_source_config():
    rules = [MandatoryFieldRule("user_info", "DataSourceConfig")]
    config = DataSourceConfig(SourceType.CONFIG_MGMT_DB, "mysql", "mysql", "localhost:3306/mysql", "")

    errors = ValidateMandatoryFields(rules).execute([config], _context())

    assert len(errors) == 1
    assert errors[0].source_name == "mysql"
    assert errors[0].source_type == "config_mgmt_db"
