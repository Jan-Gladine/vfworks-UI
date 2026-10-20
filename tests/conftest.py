"""Shared fixtures. vfworks is imported once per test run (15-25 s); frames are built in tmp dirs."""
import pytest

from vfbuilder import package_files, vfw
from vfbuilder.frame import FrameSession


def build_screw_frame(directory, package_name: str = "VF_SCREW") -> FrameSession:
    """The screw-detection validity frame from the vfWorks populatePackage.py example."""
    session = FrameSession.new(directory, package_name, name="Screw_detection_model_VF", description="...")
    package_files.create_monitor_file(session.package_root, "trust_evaluation.py")

    exp = session.add_experiment("EXP1")
    session.set(exp, "description", "Blue light experiment")
    session.add_condition(exp, "colorRed", 255)
    images = session.add_measurement(exp, "images", "dataset_metadata.yaml")

    count = session.add_specification("ScrewCount", "screws_samples", "property_min", {"valueMin": 100},
                                      description="Screw sample count")
    trust_spec = session.add_specification("ModelTrust", "label", "property_custom",
                                           description="Model trustworthiness")

    image = session.add_property("Image", description="Input image")
    trust = session.add_property("Trust", description="Model output trust")
    session.set(trust, "max", 1)
    session.set_satisfies(trust, [trust_spec.GUID])
    samples = session.add_property("DatasetSampleCount", influence_factor=True, description="...")
    session.set(samples, "datatype", "int_16")
    session.set(samples, "max", 1)
    session.set_satisfies(samples, [count.GUID])
    for prop in (image, trust, samples):
        session.set(prop, "domain", "None")
    session.set_measured_property(images, image.GUID)

    ms = session.add_model_structure("Screw_detection_model_YOLO")
    session.set(ms, "modelType", "monitoredModel")
    session.set(ms, "modelRef", "best.pt")
    inport = session.add_port(ms, "in", "image")
    session.set(inport, "description", "input image")
    session.set_mapping(inport, image.GUID)
    outport = session.add_port(ms, "out", "certainties")
    session.set_mapping(outport, trust.GUID)
    for port in (inport, outport):
        session.set(port, "domain", "None")

    session.add_monitor("SampleCountMonitor", "DataValidationTime", [count.GUID], description="...")
    session.add_monitor("TrustMonitor", "RunTime", [trust_spec.GUID], code_file="trust_evaluation.py",
                        description="...")
    return session


@pytest.fixture(scope="session", autouse=True)
def vfworks_loaded():
    return vfw.vfw()


@pytest.fixture
def screw(tmp_path):
    session = build_screw_frame(tmp_path)
    yield session
    session.close()


def by_name(items, name):
    return next(i for i in items if i.name == name)
