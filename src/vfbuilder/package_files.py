"""Files inside a package directory that the editor lists or creates from vfworks' templates.

vfworks writes ``custom_monitor_example.py`` and ``MonitoredModel_loader.py`` into every
new package; new monitor code files and model loaders start as copies of those.
"""
from __future__ import annotations

from pathlib import Path

MONITOR_TEMPLATE = "custom_monitor_example.py"
LOADER_TEMPLATE = "MonitoredModel_loader.py"


class PackageFileError(Exception):
    pass


def list_monitor_files(root: Path | None) -> list[str]:
    """Python files in ``Resources/monitors`` that can serve as a monitor's custom code."""
    return _python_files(root, "monitors")


def list_loaders(root: Path | None) -> list[str]:
    """Custom model types: ``Resources/loaders/<type>.py`` is selected by ``modelType=<type>``."""
    return [Path(name).stem for name in _python_files(root, "loaders")]


def _python_files(root: Path | None, folder: str) -> list[str]:
    if root is None:
        return []
    directory = Path(root) / "Resources" / folder
    if not directory.is_dir():
        return []
    return sorted(p.name for p in directory.glob("*.py") if p.is_file() and p.name != "__init__.py")


def create_monitor_file(root: Path, file_name: str) -> Path:
    """Create a monitor code file from the template vfworks ships in a new package."""
    return _create_from_template(Path(root) / "Resources" / "monitors", MONITOR_TEMPLATE, file_name)


def create_loader_file(root: Path, file_name: str) -> Path:
    """Create a custom model loader; its file name without ``.py`` is the model type."""
    return _create_from_template(Path(root) / "Resources" / "loaders", LOADER_TEMPLATE, file_name)


def _create_from_template(directory: Path, template_name: str, file_name: str) -> Path:
    if not file_name.endswith(".py"):
        file_name += ".py"
    if Path(file_name).name != file_name:
        raise PackageFileError("The file name must not contain a path")
    target = directory / file_name
    if target.exists():
        raise PackageFileError(f"{file_name} already exists")
    template = directory / template_name
    if not template.is_file():
        raise PackageFileError(f"Template {template_name} not found in {directory}")
    target.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    return target
