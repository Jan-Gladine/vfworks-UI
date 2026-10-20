"""FrameSession: creating, editing, saving and reopening real vfworks ValidityFrames."""
import json
import os
import subprocess
import sys
import zipfile

import pytest
from conftest import build_screw_frame, by_name

from vfbuilder import package_files, vfw
from vfbuilder.frame import FrameError, FrameSession, custom_code_file
from vfbuilder.script import render_script

SECTIONS = ("Metadata", "Operational", "Experiments", "Processes")


def read_package(root):
    return {s: json.loads((root / s / f"{s}.json").read_text(encoding="utf-8")) for s in SECTIONS}


def strip(node, keys):
    if isinstance(node, dict):
        return {k: strip(v, keys) for k, v in node.items() if k not in keys}
    if isinstance(node, list):
        return [strip(v, keys) for v in node]
    return node


def without_container_identity(package):
    # MetaData/Operational/... are created inside ValidityFrame and get a fresh GUID each time
    return {s: {k: v for k, v in data.items() if k not in ("_GUID", "_timestamp")} for s, data in package.items()}


# ----------------------------------------------------------------------- create
def test_new_frame_is_a_vfworks_package(tmp_path):
    session = FrameSession.new(tmp_path, "PKG", name="My frame")
    try:
        root = tmp_path / "PKG"
        assert session.package_root == root and session.source == root and not session.archive
        assert (root / "validity_frame.ini").is_file() and (root / "Metadata" / "Metadata.json").is_file()
        assert package_files.list_monitor_files(root) == [package_files.MONITOR_TEMPLATE]
        assert not session.dirty and session.vf.name == "My frame"
    finally:
        session.close()


@pytest.mark.parametrize("name, message", [("", "plain folder name"), ("a/b", "plain folder name"),
                                           ("demo.vf", "Leave '.vf' off")])
def test_new_frame_rejects_bad_names(tmp_path, name, message):
    with pytest.raises(FrameError, match=message):
        FrameSession.new(tmp_path, name)


def test_new_frame_refuses_to_overwrite(tmp_path):
    (tmp_path / "PKG").mkdir()
    (tmp_path / "PKG" / "something.txt").write_text("x")
    with pytest.raises(FrameError, match="already exists"):
        FrameSession.new(tmp_path, "PKG")


# --------------------------------------------------------------- saved package
def test_saved_package_has_the_links(screw):
    screw.save()
    package = read_package(screw.package_root)
    metadata, operational = package["Metadata"], package["Operational"]
    spec_guids = {s["_name"]: s["_GUID"] for s in metadata["_specifications"]}
    prop_guids = {p["_name"]: p["_GUID"] for p in metadata["_properties"]}

    assert {p["_name"]: p["_satisfies"] for p in metadata["_properties"]} == {
        "Image": [], "Trust": [spec_guids["ModelTrust"]], "DatasetSampleCount": [spec_guids["ScrewCount"]]}
    design, runtime = operational["_design_time_monitors"], operational["_runtime_monitors"]
    assert [(m["_name"], [s["_GUID"] for s in m["observes"]]) for m in design] == [
        ("SampleCountMonitor", [spec_guids["ScrewCount"]])]
    assert [(m["_name"], [s["_GUID"] for s in m["observes"]]) for m in runtime] == [
        ("TrustMonitor", [spec_guids["ModelTrust"]])]
    assert runtime[0]["_custom_code_file"] == "trust_evaluation.py" and runtime[0]["_require_custom_code_file"]
    (structure,) = operational["_modelStructures"]
    assert [(p["_name"], p["_mapping"]) for p in structure["_inports"]] == [("image", prop_guids["Image"])]
    assert [(p["_name"], p["_mapping"]) for p in structure["_outports"]] == [("certainties", prop_guids["Trust"])]
    (measurement,) = package["Experiments"]["_experiments"][0]["_measurements"]
    assert measurement["_poi"] == prop_guids["Image"]
    count = metadata["_specifications"][0]
    assert (count["_type"], count["_value"]["_valueMin"]) == ("property_min", 100)
    assert not screw.dirty


def test_saving_twice_writes_the_same_files(screw):
    screw.save()
    first = read_package(screw.package_root)
    screw.save()
    assert read_package(screw.package_root) == first


# ---------------------------------------------------------------------- reopen
def test_reopen_keeps_elements_links_and_values(screw):
    screw.save()
    root = screw.package_root
    before = {kind + ":" + e.GUID: e.name for kind, e, _ in screw.iter_elements()}
    screw.close()

    reopened = FrameSession.open(root)
    try:
        assert {kind + ":" + e.GUID: e.name for kind, e, _ in reopened.iter_elements()} == before
        count = by_name(reopened.specifications, "ScrewCount")
        assert reopened.spec_values(count) == {"valueMin": 100}
        assert [p.name for p in reopened.satisfied_by(count)] == ["DatasetSampleCount"]
        assert [m.name for m in reopened.observed_by(count)] == ["SampleCountMonitor"]
        assert custom_code_file(by_name(reopened.monitors, "TrustMonitor")) == "trust_evaluation.py"
        # repaired vfworks reload bugs
        assert [s.evaluationType for s in reopened.specifications] == ["property_min", "property_custom"]
        exp = reopened.experiments[0]
        assert exp.conditions[0].GUID != exp.GUID
        # accepted vfworks limitation: the package does not record influence factors
        assert not reopened.is_influence_factor(by_name(reopened.properties, "DatasetSampleCount"))
    finally:
        reopened.close()


def test_reopen_and_save_reproduces_the_package(screw):
    screw.save()
    root = screw.package_root
    original = read_package(root)
    screw.close()

    reopened = FrameSession.open(root)
    reopened.save()
    reopened.close()
    resaved = without_container_identity(read_package(root))
    original = without_container_identity(original)
    # accepted vfworks limitations on reload: a model structure's description is dropped ('tbd' is
    # its default), and a specification's value object gets a new GUID (nothing links to it)
    assert [m["_description"] for m in resaved["Operational"]["_modelStructures"]] == ["tbd"]
    for package in (resaved, original):
        for ms in package["Operational"]["_modelStructures"]:
            del ms["_description"]
        operational = package["Operational"]
        for spec in package["Metadata"]["_specifications"] + [
                s for m in operational["_design_time_monitors"] + operational["_runtime_monitors"] for s in m["observes"]]:
            del spec["_value"]["_GUID"], spec["_value"]["_timestamp"]
    assert resaved == original


def test_frames_in_one_process_do_not_share_elements(tmp_path):
    first = build_screw_frame(tmp_path / "a")
    first.save()
    second = FrameSession.new(tmp_path / "b", "EMPTY")
    try:
        assert (second.model_structures, second.monitors) == ([], [])
        second.add_model_structure("only_here")
        assert [m.name for m in first.model_structures] == ["Screw_detection_model_YOLO"]
        third = FrameSession.open(first.package_root)
        assert [m.name for m in third.model_structures] == ["Screw_detection_model_YOLO"]
        assert len(third.monitors) == 2
        third.close()
    finally:
        first.close()
        second.close()


def test_open_rejects_a_folder_that_is_no_package(tmp_path):
    (tmp_path / "random").mkdir()
    with pytest.raises(FrameError, match="not a validity frame package"):
        FrameSession.open(tmp_path / "random")


# ----------------------------------------------------------------------- edits
def test_changing_spec_type_rebuilds_it_with_the_same_guid(screw):
    spec = by_name(screw.specifications, "ScrewCount")
    monitor = by_name(screw.monitors, "SampleCountMonitor")
    new = screw.set_spec_type(spec, "property_range")

    assert new is not spec and new.GUID == spec.GUID and new.evaluationType == "property_range"
    assert screw.spec_values(new) == {"valueMin": 100, "valueMax": 0, "granularity": 10}
    rebuilt = by_name(screw.monitors, "SampleCountMonitor")
    assert rebuilt.GUID == monitor.GUID and rebuilt.observes == [new]
    assert [p.name for p in screw.satisfied_by(new)] == ["DatasetSampleCount"]  # links are GUIDs

    screw.set_spec_type(new, "property_custom")
    assert by_name(screw.monitors, "SampleCountMonitor")._require_custom_code_file is True
    assert screw.dirty


def test_spec_values_and_custom_description(screw):
    spec = by_name(screw.specifications, "ScrewCount")
    value_guid = spec.value.GUID
    screw.set_spec_value(spec, "valueMin", 250)
    assert screw.spec_values(spec) == {"valueMin": 250} and spec.value.GUID == value_guid
    custom = by_name(screw.specifications, "ModelTrust")
    screw.set(custom, "description", "Trust above threshold")
    assert custom.value.tostring() == "Trust above threshold"


def test_feature_change_rekeys_monitor_status(screw):
    spec = by_name(screw.specifications, "ScrewCount")
    screw.set_feature(spec, "n_screws")
    assert by_name(screw.monitors, "SampleCountMonitor").spec_status == {"n_screws": "unknown"}


def test_property_kind_change_keeps_guid_and_links(screw):
    prop = by_name(screw.properties, "Trust")
    new = screw.set_property_kind(prop, True)
    assert screw.is_influence_factor(new) and new.GUID == prop.GUID and new.satisfies == prop.satisfies
    assert screw.properties.index(new) == 1
    assert screw.model_structures[0].outports[0].mapping == new.GUID


def test_monitor_time_moves_it_between_lists(screw):
    monitor = by_name(screw.monitors, "SampleCountMonitor")
    new = screw.set_monitor_time(monitor, "RunTime")
    assert new.GUID == monitor.GUID
    assert [m.name for m in screw.vf.design_time_monitors] == []
    assert [m.name for m in screw.vf.runtime_monitors] == ["TrustMonitor", "SampleCountMonitor"]


def test_observes_and_code_file(screw):
    monitor = by_name(screw.monitors, "SampleCountMonitor")
    trust = by_name(screw.specifications, "ModelTrust")
    new = screw.set_observes(monitor, [s.GUID for s in screw.specifications])
    assert new.spec_status == {"screws_samples": "unknown", "label": "unknown"}
    assert new._require_custom_code_file is True and trust in new.observes
    new = screw.set_code_file(new, "trust_evaluation.py")
    assert custom_code_file(new) == "trust_evaluation.py" and new.validate_point_function is not None


def test_links_from_both_ends(screw):
    spec = by_name(screw.specifications, "ScrewCount")
    image = by_name(screw.properties, "Image")
    screw.set_satisfied_by(spec, [image.GUID])
    assert image.satisfies == [spec.GUID] and by_name(screw.properties, "DatasetSampleCount").satisfies == []
    screw.set_satisfies(image, [])
    assert screw.satisfied_by(spec) == []


def test_delete_specification_removes_links(screw):
    spec = by_name(screw.specifications, "ModelTrust")
    refs = screw.delete(spec)
    assert {(r.owner_kind, r.owner_name, r.relation) for r in refs} == {
        ("property", "Trust", "satisfies"), ("monitor", "TrustMonitor", "observes")}
    assert spec not in screw.specifications
    assert by_name(screw.properties, "Trust").satisfies == []
    assert by_name(screw.monitors, "TrustMonitor").observes == []


def test_delete_property_and_nested_elements(screw):
    image = by_name(screw.properties, "Image")
    refs = screw.delete(image)
    assert sorted(str(r) for r in refs) == ["inport 'Screw_detection_model_YOLO.image' (mapped to)",
                                            "measurement 'EXP1.images' (measures)"]
    ms, exp = screw.model_structures[0], screw.experiments[0]
    assert ms.inports[0].mapping is None and exp.measurements[0].poi is None
    screw.delete(ms.outports[0])
    screw.delete(exp.conditions[0])
    screw.delete(by_name(screw.monitors, "TrustMonitor"))
    assert ms.outports == [] and exp.conditions == [] and [m.name for m in screw.monitors] == ["SampleCountMonitor"]


# --------------------------------------------------------------------- archive
def test_archive_save_open_and_resave(screw):
    archive = screw.save_archive()
    assert archive == screw.package_root.with_name("VF_SCREW.vf") and zipfile.is_zipfile(archive)
    screw.close()

    session = FrameSession.open(archive)
    try:
        assert session.archive and session.package_name == "VF_SCREW"
        assert session.package_root != archive.with_suffix("")  # vfworks' temporary working copy
        session.add_specification("Extra", "extra", "property_max", {"valueMax": 3})
        session.save()  # export() re-zips the archive
    finally:
        session.close()
    reopened = FrameSession.open(archive)
    try:
        assert [s.name for s in reopened.specifications] == ["ScrewCount", "ModelTrust", "Extra"]
    finally:
        reopened.close()


# ---------------------------------------------------------------------- script
def test_generated_script_builds_the_same_package(screw, tmp_path):
    screw.save()
    work = tmp_path / "script"
    work.mkdir()
    root = work / screw.package_name
    vfw.vfw().PackageManager(packageName=root.name, packageLocation=work).create(name=root.name, standalone=True)
    package_files.create_monitor_file(root, "trust_evaluation.py")
    (work / "populatePackage.py").write_text(render_script(screw), encoding="utf-8")

    done = subprocess.run([sys.executable, "populatePackage.py"], cwd=work, capture_output=True, text=True,
                          env={**os.environ, "MPLBACKEND": "Agg"})

    assert done.returncode == 0, done.stdout + done.stderr
    # the script pins element GUIDs but not timestamps or the GUIDs of spec value objects
    ours = strip(without_container_identity(read_package(screw.package_root)), ("_timestamp",))
    theirs = strip(without_container_identity(read_package(root)), ("_timestamp",))
    for package in (ours, theirs):
        for spec in package["Metadata"]["_specifications"]:
            del spec["_value"]["_GUID"]
        for monitor in package["Operational"]["_design_time_monitors"] + package["Operational"]["_runtime_monitors"]:
            for spec in monitor["observes"]:
                del spec["_value"]["_GUID"]
    assert theirs == ours


def test_catalog_comes_from_vfworks():
    enums = vfw.enums()
    assert enums["PropertyType"]["PROPERTY_MIN"] == "property_min"
    assert set(enums["MonitorTime"]) == {"DATA_VALIDATION", "MODEL_VALIDATION", "RUN_TIME"}
    assert vfw.spec_value_fields("property_range") == ("valueMin", "valueMax", "granularity")
    assert vfw.spec_value_fields("property_custom") == ()
    assert vfw.builtin_model_types() == ["pycaret", "YOLO", "torch"]
    assert vfw.enum_name("MonitorTime", "RunTime") == "RUN_TIME"


def test_archive_with_the_package_one_folder_down_is_refused(screw, tmp_path):
    # made by zipping the package folder itself, as Explorer's "Compress" does
    screw.save()
    archive = tmp_path / "wrapped.vf"
    with zipfile.ZipFile(archive, "w") as zf:
        for item in screw.package_root.rglob("*"):
            zf.write(item, (screw.package_root.name / item.relative_to(screw.package_root)).as_posix())
    with pytest.raises(FrameError, match="one folder down .*open the VF_SCREW folder"):
        FrameSession.open(archive)
    (tmp_path / "not_a_package.vf").write_bytes(b"not a zip")
    with pytest.raises(FrameError, match="not a zip archive"):
        FrameSession.open(tmp_path / "not_a_package.vf")
