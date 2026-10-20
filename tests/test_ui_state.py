"""The UI's state and graph helpers; neither needs a browser."""
import pytest
from conftest import build_screw_frame, by_name

from vfbuilder.frame import FrameError
from vfbuilder.graph import element_id_of, mermaid_source, node_id
from vfbuilder.ui.state import AppState


@pytest.fixture
def state(tmp_path):
    state = AppState()
    state._replace(build_screw_frame(tmp_path))
    yield state
    state.close()


def test_catalog_feeds_the_dropdowns(state):
    assert state.enums["PropertyType"]["PROPERTY_CUSTOM"] == "property_custom"
    assert state.enums["UnitType"]["UNIT_none"] == "-"
    assert "YOLO" in state.builtin_model_types


def test_severity_includes_nested_elements(state):
    s = state.session
    ms = s.model_structures[0]
    assert state.severity(ms) == "warning"  # no loader for monitoredModel
    ms.inports[0].name = ""
    state.touch()
    assert state.severity(ms) == "error"


def test_locate_maps_nested_elements_to_their_parent(state):
    s = state.session
    ms, exp = s.model_structures[0], s.experiments[0]
    assert state.locate(s.specifications[0].GUID) == ("specifications", s.specifications[0].GUID)
    assert state.locate(ms.outports[0].GUID) == ("structures", ms.GUID)
    assert state.locate(exp.measurements[0].GUID) == ("experiments", exp.GUID)
    assert state.locate(s.monitors[1].GUID) == ("monitors", s.monitors[1].GUID)
    assert state.locate("nope") is None


def test_feature_suggestions(state):
    spec = by_name(state.session.specifications, "ScrewCount")
    assert state.feature_suggestions() == ["colorRed", "images", "label", "screws_samples"]
    assert state.feature_suggestions(exclude=spec) == ["colorRed", "images", "label"]


def test_new_open_close(tmp_path, state):
    root = state.session.package_root
    state.session.save()
    state.new(tmp_path / "other", "SECOND")
    assert state.session.package_name == "SECOND" and state.session.specifications == []
    state.open(root)
    assert [sp.name for sp in state.session.specifications] == ["ScrewCount", "ModelTrust"]
    state.close()
    assert state.session is None and state.issues == []
    with pytest.raises(FrameError):
        state.open(tmp_path / "missing")


# ------------------------------------------------------------------------ graph
def test_graph_has_a_node_per_element_and_an_edge_per_link(state):
    s = state.session
    source = mermaid_source(s, state.severity)
    image, trust, count = s.properties
    spec_count, spec_trust = s.specifications
    inport, outport = s.model_structures[0].inports[0], s.model_structures[0].outports[0]

    assert source.startswith("flowchart LR")
    for element in (*s.properties, *s.specifications, *s.monitors, inport, outport):
        assert f"    {node_id(element.GUID)}" in source
    assert f"{node_id(inport.GUID)} --> {node_id(image.GUID)}" in source
    assert f"{node_id(outport.GUID)} --> {node_id(trust.GUID)}" in source
    assert f"{node_id(trust.GUID)} -->|satisfies| {node_id(spec_trust.GUID)}" in source
    assert f"{node_id(count.GUID)} -->|satisfies| {node_id(spec_count.GUID)}" in source
    assert f"{node_id(spec_trust.GUID)} -->|observed by| {node_id(s.monitors[1].GUID)}" in source
    assert source.count("-->") == 6
    assert "influence factor" in source


def test_graph_highlights_issues_and_escapes_names(state):
    s = state.session
    spec = by_name(s.specifications, "ScrewCount")
    s.set(spec, "name", 'Screw "count" <b>')
    monitor = s.set_observes(by_name(s.monitors, "SampleCountMonitor"), [])
    state.touch()

    source = mermaid_source(s, state.severity)

    assert "Screw #quot;count#quot; #lt;b#gt;" in source and '"count"' not in source
    assert f"class {node_id(monitor.GUID)} error" in source
    assert node_id(spec.GUID) in source.split("class ")[-1]  # flagged: no longer observed
    assert source.count("-->") == 5


def test_graph_node_ids_round_trip(state):
    guid = state.session.properties[0].GUID
    assert element_id_of(node_id(guid)) == guid
    assert element_id_of(f"flowchart-{node_id(guid)}-12") == guid
    assert element_id_of("something-else") is None
