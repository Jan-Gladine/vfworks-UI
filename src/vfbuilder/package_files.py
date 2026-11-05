"""Code files inside a package: monitor functions and model loaders.

vfworks writes ``custom_monitor_example.py`` and ``MonitoredModel_loader.py`` into every
new package; new monitor code files and model loaders start as copies of those.
Files are only read, written and parsed here, never imported: vfworks itself imports
them when a monitor is added (``Resources/monitors``) or a model is loaded
(``Resources/loaders``).
"""
from __future__ import annotations

import ast
import os
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

MONITORS = "monitors"
LOADERS = "loaders"
FOLDERS = (MONITORS, LOADERS)
MONITOR_TEMPLATE = "custom_monitor_example.py"
LOADER_TEMPLATE = "MonitoredModel_loader.py"
TEMPLATES = {MONITORS: MONITOR_TEMPLATE, LOADERS: LOADER_TEMPLATE}
# the function vfworks looks up in each kind of file
REQUIRED_FUNCTION = {MONITORS: "validate", LOADERS: "load_model"}


class PackageFileError(Exception):
    pass


def list_monitor_files(root: Path | None) -> list[str]:
    """Python files in ``Resources/monitors`` that can serve as a monitor's custom code."""
    return list_code_files(root, MONITORS)


def list_loaders(root: Path | None) -> list[str]:
    """Custom model types: ``Resources/loaders/<type>.py`` is selected by ``modelType=<type>``."""
    return [Path(name).stem for name in list_code_files(root, LOADERS)]


def list_code_files(root: Path | None, folder: str) -> list[str]:
    if root is None:
        return []
    directory = Path(root) / "Resources" / folder
    if not directory.is_dir():
        return []
    return sorted(p.name for p in directory.glob("*.py") if p.is_file() and p.name != "__init__.py")


def code_path(root: Path, folder: str, file_name: str) -> Path:
    """``<root>/Resources/<folder>/<file_name>``, refusing anything that would leave that folder."""
    if folder not in FOLDERS:
        raise PackageFileError(f"Unknown code folder '{folder}'")
    if not file_name.endswith(".py"):
        file_name += ".py"
    if Path(file_name).name != file_name or file_name in (".py", "__init__.py"):
        raise PackageFileError("The file name must be a plain .py file name")
    return Path(root) / "Resources" / folder / file_name


def read_code(root: Path, folder: str, file_name: str) -> str:
    try:
        return code_path(root, folder, file_name).read_text(encoding="utf-8")
    except OSError as exc:
        raise PackageFileError(f"Cannot read {file_name}: {exc}") from exc


def write_code(root: Path, folder: str, file_name: str, text: str) -> Path:
    """Write atomically, so a failed save never leaves a half-written file."""
    target = code_path(root, folder, file_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_name, target)
    except OSError as exc:
        raise PackageFileError(f"Cannot write {target.name}: {exc}") from exc
    finally:
        Path(tmp_name).unlink(missing_ok=True)
    return target


def delete_code(root: Path, folder: str, file_name: str) -> None:
    path = code_path(root, folder, file_name)
    if path.name == TEMPLATES[folder]:
        raise PackageFileError(f"{path.name} is the template vfworks copies new files from")
    try:
        path.unlink()
    except OSError as exc:
        raise PackageFileError(f"Cannot delete {path.name}: {exc}") from exc


def create_monitor_file(root: Path, file_name: str) -> Path:
    """Create a monitor code file from the template vfworks ships in a new package."""
    return create_from_template(root, MONITORS, file_name)


def create_loader_file(root: Path, file_name: str) -> Path:
    """Create a custom model loader; its file name without ``.py`` is the model type."""
    return create_from_template(root, LOADERS, file_name)


def create_from_template(root: Path, folder: str, file_name: str) -> Path:
    target = code_path(root, folder, file_name)
    if target.exists():
        raise PackageFileError(f"{target.name} already exists")
    template = target.parent / TEMPLATES[folder]
    if not template.is_file():
        raise PackageFileError(f"Template {template.name} not found in {target.parent}")
    target.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    return target


# --------------------------------------------------------------------- checks
@dataclass(frozen=True)
class CodeIssue:
    severity: Literal["error", "warning"]
    line: int | None  # 1-based
    message: str

    def __str__(self) -> str:
        return f"line {self.line}: {self.message}" if self.line else self.message


def check_code(text: str, folder: str) -> list[CodeIssue]:
    """Static checks against what vfworks expects; the code is parsed, never run."""
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [CodeIssue("error", exc.lineno, f"Syntax error: {exc.msg}")]
    name = REQUIRED_FUNCTION[folder]
    function = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name), None)
    if function is None:
        if folder == MONITORS:
            why = "vfworks then ignores the file and uses the built-in checks"
        else:
            why = "vfworks cannot load the model"
        return [CodeIssue("warning", None, f"No top-level function {name}(); {why}")]

    issues: list[CodeIssue] = []
    args = function.args
    if folder == MONITORS and args.kwarg is None:
        issues.append(CodeIssue("warning", function.lineno,
                                "validate() should accept **kwargs: vfworks calls it with data_vector=..., "
                                "monitor=... and every feature as a keyword argument"))
    if folder == LOADERS and not (args.posonlyargs or args.args or args.vararg):
        issues.append(CodeIssue("warning", function.lineno,
                                "load_model() is called with the model location as first argument"))
    for node in ast.walk(function):
        if isinstance(node, ast.Raise) and _names_not_implemented(node.exc):
            issues.append(CodeIssue("warning", node.lineno,
                                    f"{name}() still raises NotImplementedError (template code)"))
            break
    return issues


def _names_not_implemented(exc: ast.expr | None) -> bool:
    target = exc.func if isinstance(exc, ast.Call) else exc
    return isinstance(target, ast.Name) and target.id == "NotImplementedError"


def check_file(root: Path, folder: str, file_name: str) -> list[CodeIssue]:
    """``check_code`` for a file on disk, cached until the file changes."""
    path = code_path(root, folder, file_name)
    try:
        stat = path.stat()
    except OSError:
        return []
    return list(_check_cached(str(path), folder, stat.st_mtime_ns, stat.st_size))


@lru_cache(maxsize=256)
def _check_cached(path: str, folder: str, _mtime_ns: int, _size: int) -> tuple[CodeIssue, ...]:
    try:
        return tuple(check_code(Path(path).read_text(encoding="utf-8"), folder))
    except (OSError, UnicodeDecodeError) as exc:
        return (CodeIssue("error", None, f"Cannot read the file: {exc}"),)
