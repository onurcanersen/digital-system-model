from datetime import datetime
from pathlib import Path

from fakes.fake_source_code_repository import FakeSourceCodeRepository
from model.acquired_file import AcquiredFile
from model.inventory import SoftwareUnitVersion, SoftwareUnitVersionInventory
from model.project_context import AcquisitionContext, PlatformRecord, ProjectRecord, VersionRecord
from model.status import AcquisitionStatus
from ports.source_code_repository import SourceRepoAccessError, SourceRepoAuthError, SourceRepoIntegrityError
from use_cases.fetch_source_files import FetchSourceFilesUseCase


def _inventory(units) -> SoftwareUnitVersionInventory:
    context = AcquisitionContext(
        project=ProjectRecord("proj-1", "skywatch"),
        platform=PlatformRecord("plat-1", "proj-1", "nftw"),
        version=VersionRecord("1.0.0", "proj-1", "plat-1", "1.0.0", is_effective=True),
    )
    return SoftwareUnitVersionInventory(context=context, units=units)


def test_records_only_the_mandatory_subset_regardless_of_tree_size():
    # Simulates a real repo with many source files (NavApp.java, Utils.java, ...) —
    # only the two mandatory manifest files should ever produce a record.
    mandatory = ["Makefile", "src/unit.xml"]
    found = [AcquiredFile("nav_app", "Makefile", "Makefile", "1.0.0", datetime.now())]
    repo = FakeSourceCodeRepository(mandatory_files=mandatory, clone_results={"nav_app": found})
    inventory = _inventory([SoftwareUnitVersion("nav_app", "1.0.0")])

    results = FetchSourceFilesUseCase(repo).execute(inventory, Path("/tmp/msd-test"))

    assert len(results) == len(mandatory)
    by_name = {r.file_name: r for r in results}
    assert by_name["Makefile"].status == AcquisitionStatus.OK
    assert by_name["unit.xml"].status == AcquisitionStatus.MISSING_DATA


def test_reports_access_error_for_every_mandatory_file():
    repo = FakeSourceCodeRepository(mandatory_files=["Makefile"], raise_error=SourceRepoAccessError("repo not found"))
    inventory = _inventory([SoftwareUnitVersion("sensor_app", "1.0.0")])

    results = FetchSourceFilesUseCase(repo).execute(inventory, Path("/tmp/msd-test"))

    assert len(results) == 1
    assert results[0].status == AcquisitionStatus.ERROR
    assert results[0].errors[0].error_type == "access"


def test_reports_authorization_error():
    repo = FakeSourceCodeRepository(mandatory_files=["Makefile"], raise_error=SourceRepoAuthError("bad credentials"))
    inventory = _inventory([SoftwareUnitVersion("sensor_app", "1.0.0")])

    results = FetchSourceFilesUseCase(repo).execute(inventory, Path("/tmp/msd-test"))

    assert results[0].errors[0].error_type == "authorization"


def test_reports_integrity_error():
    repo = FakeSourceCodeRepository(mandatory_files=["Makefile"], raise_error=SourceRepoIntegrityError("corrupt file"))
    inventory = _inventory([SoftwareUnitVersion("sensor_app", "1.0.0")])

    results = FetchSourceFilesUseCase(repo).execute(inventory, Path("/tmp/msd-test"))

    assert results[0].errors[0].error_type == "integrity"
