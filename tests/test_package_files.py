"""Code files in a package: reading, writing and the static checks."""
import pytest

from vfbuilder import package_files as pf
from vfbuilder.frame import FrameSession
from vfbuilder.validator import validate


@pytest.fixture
def root(tmp_path):
    session = FrameSession.new(tmp_path, "PKG")
    yield session.package_root
    session.close()


def test_templates_are_listed_and_new_files_copy_them(root):
    assert pf.list_code_files(root, pf.MONITORS) == [pf.MONITOR_TEMPLATE]
    assert pf.list_loaders(root) == ["MonitoredModel_loader"]
    created = pf.create_from_template(root, pf.LOADERS, "yolo_loader")
    assert created.name == "yolo_loader.py" and "def load_model" in created.read_text(encoding="utf-8")
    with pytest.raises(pf.PackageFileError, match="already exists"):
        pf.create_from_template(root, pf.LOADERS, "yolo_loader.py")


def test_write_read_delete(root):
    pf.write_code(root, pf.MONITORS, "m.py", "def validate(monitor=None, **kwargs):\n    return {}\n")
    assert pf.read_code(root, pf.MONITORS, "m.py").startswith("def validate")
    assert pf.list_monitor_files(root) == [pf.MONITOR_TEMPLATE, "m.py"]
    pf.delete_code(root, pf.MONITORS, "m.py")
    assert pf.list_monitor_files(root) == [pf.MONITOR_TEMPLATE]
    with pytest.raises(pf.PackageFileError, match="template"):
        pf.delete_code(root, pf.MONITORS, pf.MONITOR_TEMPLATE)


@pytest.mark.parametrize("name", ["../evil.py", "a/b.py", "__init__.py", ".py"])
def test_paths_stay_inside_the_folder(root, name):
    with pytest.raises(pf.PackageFileError):
        pf.write_code(root, pf.MONITORS, name, "x = 1\n")
    with pytest.raises(pf.PackageFileError, match="Unknown code folder"):
        pf.code_path(root, "Metadata", "x.py")


@pytest.mark.parametrize("folder, code, expected", [
    (pf.MONITORS, "def validate(monitor=None, **kwargs):\n    return {}\n", []),
    (pf.MONITORS, "def validate(monitor=None, **kwargs)\n    return {}\n", [("error", 1, "Syntax error")]),
    (pf.MONITORS, "x = 1\n", [("warning", None, "No top-level function validate()")]),
    (pf.MONITORS, "def validate(monitor=None):\n    return {}\n", [("warning", 1, "should accept **kwargs")]),
    (pf.LOADERS, "def load_model():\n    pass\n", [("warning", 1, "model location as first argument")]),
    (pf.LOADERS, "def load_model(model_location, validityframe=None):\n    raise NotImplementedError('todo')\n",
     [("warning", 2, "still raises NotImplementedError")]),
])
def test_check_code(folder, code, expected):
    issues = pf.check_code(code, folder)
    assert [(i.severity, i.line) for i in issues] == [(s, line) for s, line, _ in expected]
    for issue, (_, _, text) in zip(issues, expected):
        assert text in issue.message


def test_templates_are_flagged_as_unfinished(root):
    issues = pf.check_file(root, pf.MONITORS, pf.MONITOR_TEMPLATE)
    assert [i.severity for i in issues] == ["warning"] and "NotImplementedError" in issues[0].message


def test_validation_reports_problems_in_used_code_files(screw):
    root = screw.package_root
    pf.write_code(root, pf.MONITORS, "trust_evaluation.py", "def validate(:\n")
    pf.create_loader_file(root, "monitoredModel")
    issues = [(i.severity, i.message) for i in validate(screw)]
    assert ("error", "Code file trust_evaluation.py, line 1: Syntax error: invalid syntax") in issues
    assert ("warning", "Loader monitoredModel.py, line 53: load_model() still raises NotImplementedError "
                       "(template code)") in issues
