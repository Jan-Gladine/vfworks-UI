import pytest
from conftest import by_name

from vfbuilder import package_files
from vfbuilder.frame import FrameSession
from vfbuilder.validator import has_errors, validate


def messages(session, severity, element=None):
    return [i.message for i in validate(session)
            if i.severity == severity and (element is None or i.element_id == element.GUID)]


@pytest.fixture
def empty(tmp_path):
    session = FrameSession.new(tmp_path, "PKG")
    yield session
    session.close()


def test_screw_frame_has_only_the_loader_warning(screw):
    assert [(i.severity, i.message) for i in validate(screw)] == [
        ("warning", "Model type 'monitoredModel' is not built in and Resources/loaders/monitoredModel.py "
                    "does not exist in the package")]
    package_files.create_loader_file(screw.package_root, "monitoredModel")
    assert validate(screw) == []


# ------------------------------------------------------------------------ names
def test_empty_names_are_errors(empty):
    spec = empty.add_specification("", "f", "property_custom")
    assert "This specification needs a name" in messages(empty, "error", spec)


def test_names_unique_across_specs_properties_monitors(screw):
    spec = by_name(screw.specifications, "ScrewCount")
    prop = by_name(screw.properties, "Image")
    screw.set(prop, "name", "ScrewCount")
    for element in (spec, prop):
        assert any("across specifications, properties and monitors" in m for m in messages(screw, "error", element))


def test_names_unique_within_type(screw):
    ms = screw.model_structures[0]
    port = screw.add_port(ms, "in", "image")
    screw.add_experiment("EXP1")
    errors = messages(screw, "error")
    assert any("among the inports" in m for m in errors) and any("among experiments" in m for m in errors)
    assert any("among the inports" in m for m in messages(screw, "error", port))


# --------------------------------------------------------------- specifications
@pytest.mark.parametrize("low, high, ok", [(0, 1, True), (1, 1, False), (2, 1, False)])
def test_range_min_below_max(empty, low, high, ok):
    spec = empty.add_specification("S", "f", "property_range", {"valueMin": low, "valueMax": high})
    assert ("valueMin must be smaller than valueMax" in messages(empty, "error", spec)) is not ok


@pytest.mark.parametrize("granularity", [0, -1, 2.5])
def test_range_granularity_is_a_positive_whole_number(empty, granularity):
    spec = empty.add_specification("S", "f", "property_range", {"valueMin": 0, "valueMax": 1, "granularity": granularity})
    assert any("granularity" in m for m in messages(empty, "error", spec))


def test_spec_needs_a_feature(empty):
    spec = empty.add_specification("S", "", "property_min")
    assert any(m.startswith("Feature is required") for m in messages(empty, "error", spec))


def test_unlinked_spec_warnings(empty):
    spec = empty.add_specification("S", "f", "property_custom")
    assert messages(empty, "warning", spec) == ["Not satisfied by any property", "Not observed by any monitor"]


# ------------------------------------------------------------------- monitors
def test_monitor_must_observe_a_spec(empty):
    monitor = empty.add_monitor("M")
    assert "A monitor must observe at least one specification" in messages(empty, "error", monitor)


def test_monitor_on_custom_spec_needs_code_file(screw):
    monitor = screw.set_code_file(by_name(screw.monitors, "TrustMonitor"), None)
    assert messages(screw, "error", monitor) == [
        "Observes custom specification(s) ModelTrust and needs a custom code file"]


def test_missing_code_file_warns(screw):
    monitor = screw.set_code_file(by_name(screw.monitors, "TrustMonitor"), "gone.py")
    assert any("'gone.py' does not exist" in m for m in messages(screw, "warning", monitor))


def test_monitor_feature_collision_warning(screw):
    monitor = by_name(screw.monitors, "SampleCountMonitor")
    other = screw.add_specification("ScrewCountMax", "screws_samples", "property_max", {"valueMax": 5000})
    monitor = screw.set_observes(monitor, [s.GUID for s in monitor.observes] + [other.GUID])
    assert messages(screw, "warning", monitor) == [
        "Observed specifications ScrewCount, ScrewCountMax share feature 'screws_samples'; "
        "their status in this monitor will collide"]


# ------------------------------------------------------- properties and ports
def test_property_min_above_max_warns(screw):
    prop = by_name(screw.properties, "Trust")
    screw.set(prop, "min", 2)
    assert messages(screw, "warning", prop) == ["min (2) is greater than max (1)"]


def test_unmapped_port_warns(screw):
    port = screw.model_structures[0].outports[0]
    screw.set_mapping(port, None)
    assert messages(screw, "warning", port) == ["Outport is not mapped to a property"]


def test_unknown_enum_value_is_an_error(screw):
    prop = by_name(screw.properties, "Image")
    screw.set(prop, "unit", "parsec")
    assert "Unit 'parsec' is not a UnitType of the installed vfworks" in messages(screw, "error", prop)


def test_dangling_links_are_errors(screw):
    prop = by_name(screw.properties, "Image")
    prop.satisfies = ["gone"]  # e.g. a hand-edited package
    screw.model_structures[0].inports[0].mapping = "gone"
    errors = messages(screw, "error")
    assert "Satisfies a specification that does not exist" in errors
    assert "Mapped to a property that does not exist" in errors
    assert has_errors(validate(screw))


def test_measurements_with_one_name_and_different_properties_warn(screw):
    exp = screw.add_experiment("EXP2")
    meas = screw.add_measurement(exp, "images")
    screw.set_measured_property(meas, by_name(screw.properties, "Trust").GUID)
    assert any("assign_poi2measurement" in m for m in messages(screw, "warning", meas))
