from fakes.fake_config_management_repository import FakeConfigManagementRepository
from model.status import AcquisitionStatus
from ports.config_management_repository import ConfigManagementAccessError
from use_cases.acquire_project_context import AcquireProjectContextUseCase


def test_execute_returns_context_when_explicit_ids_match():
    repo = FakeConfigManagementRepository()

    result = AcquireProjectContextUseCase(repo).execute(
        project_id="proj-1", platform_id="plat-1", version_id="1.0.0"
    )

    assert result.status == AcquisitionStatus.OK
    assert result.context is not None
    assert result.context.project.name == "skywatch"
    assert result.context.version.is_effective is True


def test_execute_marks_missing_data_when_project_id_not_specified():
    repo = FakeConfigManagementRepository()

    result = AcquireProjectContextUseCase(repo).execute(platform_id="plat-1", version_id="1.0.0")

    assert result.status == AcquisitionStatus.MISSING_DATA
    assert result.context is None
    assert "project_id" in result.error.reason


def test_execute_marks_missing_data_when_platform_id_not_specified():
    repo = FakeConfigManagementRepository()

    result = AcquireProjectContextUseCase(repo).execute(project_id="proj-1", version_id="1.0.0")

    assert result.status == AcquisitionStatus.MISSING_DATA
    assert "platform_id" in result.error.reason


def test_execute_marks_missing_data_when_version_id_not_specified():
    repo = FakeConfigManagementRepository()

    result = AcquireProjectContextUseCase(repo).execute(project_id="proj-1", platform_id="plat-1")

    assert result.status == AcquisitionStatus.MISSING_DATA
    assert "version_id" in result.error.reason


def test_execute_marks_missing_data_when_project_id_not_found():
    repo = FakeConfigManagementRepository()

    result = AcquireProjectContextUseCase(repo).execute(
        project_id="does-not-exist", platform_id="plat-1", version_id="1.0.0"
    )

    assert result.status == AcquisitionStatus.MISSING_DATA
    assert "does-not-exist" in result.error.reason


def test_execute_marks_error_status_on_config_management_access_error():
    repo = FakeConfigManagementRepository(raise_error=ConfigManagementAccessError("db unreachable"))

    result = AcquireProjectContextUseCase(repo).execute(
        project_id="proj-1", platform_id="plat-1", version_id="1.0.0"
    )

    assert result.status == AcquisitionStatus.ERROR
    assert result.context is None
    assert result.error is not None
    assert "db unreachable" in result.error.reason
