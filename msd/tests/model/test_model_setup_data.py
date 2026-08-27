from datetime import datetime

from model.acquired_file import AcquiredFile
from model.inventory import SoftwareUnitVersion, SoftwareUnitVersionInventory
from model.model_setup_data import ModelSetupData, ModelSetupDataTopic
from model.project_context import ProjectContext, PlatformRecord, ProjectRecord, VersionRecord


def _context() -> ProjectContext:
    return ProjectContext(
        project=ProjectRecord("proj-1", "skywatch"),
        platform=PlatformRecord("plat-1", "proj-1", "nftw"),
        version=VersionRecord("1.0.0", "proj-1", "plat-1", "1.0.0", is_effective=True),
    )


def test_model_setup_data_to_dict_shape():
    context = _context()
    inventory = SoftwareUnitVersionInventory(context=context, units=[SoftwareUnitVersion("nav_app", "1.0.0")])
    acquired = [AcquiredFile("nav_app", "Makefile", "/tmp/nav_app/Makefile", "1.0.0", datetime.now())]
    data = ModelSetupData(context=context, inventory=inventory, acquired_files=acquired, graph={"nodes": []})

    result = data.to_dict()

    assert result["context"]["project"]["name"] == "skywatch"
    assert result["inventory"]["units"][0]["unit_name"] == "nav_app"
    assert result["acquired_files"][0]["file_name"] == "Makefile"
    assert result["validation_errors"] == []
    assert "generated_at" in result
    assert result["graph"] == {"nodes": []}


def test_model_setup_data_topic_equality_by_name():
    a = ModelSetupDataTopic(name="nav_position", size=128)
    b = ModelSetupDataTopic(name="nav_position", size=999)
    assert a == b
    assert len({a, b}) == 1
