"""Access to vfworks: the (slow) import, the constants catalog and frame construction.

Importing the full vfworks stack pulls in torch, ultralytics and pycaret and takes
15-25 s, so it runs once in a background thread (``LOADER``) while the app starts.
The constants, the specification classes and the package manager are cheap and are
imported directly where needed.
"""
from __future__ import annotations

import collections
import inspect
import logging
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Callable


class VfworksUnavailable(RuntimeError):
    pass


class _Loader:
    """Imports vfworks once, in the background."""

    def __init__(self) -> None:
        self._started = False
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._modules: SimpleNamespace | None = None
        self.error: str | None = None
        self.seconds: float | None = None

    def start(self) -> None:
        with self._lock:
            if not self._started:
                self._started = True
                threading.Thread(target=self._load, name="vfworks-import", daemon=True).start()

    @property
    def ready(self) -> bool:
        return self._done.is_set() and self._modules is not None

    @property
    def done(self) -> bool:
        return self._done.is_set()

    def wait(self, timeout: float | None = None) -> SimpleNamespace:
        self.start()
        if not self._done.wait(timeout):
            raise VfworksUnavailable("vfworks is still loading")
        if self._modules is None:
            raise VfworksUnavailable(f"vfworks could not be imported: {self.error}")
        return self._modules

    def _load(self) -> None:
        started = time.perf_counter()
        try:
            # vfworks imports pyplot, and its graph helpers call plt.show()
            os.environ["MPLBACKEND"] = "Agg"
            # pycaret (imported by vfworks) otherwise creates logs.log in the current directory
            os.environ.setdefault("PYCARET_CUSTOM_LOGGING_PATH",
                                  str(Path(tempfile.gettempdir()) / "vfbuilder_pycaret.log"))
            import matplotlib

            matplotlib.use("Agg")
            import vfworks
            from vfworks.metamodels import experiment, model_structure, monitors, properties, specification
            from vfworks.metamodels.validity_frame import Operational, ValidityFrame
            from vfworks.package.PackageManager import PackageManager
            from vfworks.utils import constants

            self._modules = SimpleNamespace(
                version=vfworks.__version__, ValidityFrame=ValidityFrame, Operational=Operational,
                PackageManager=PackageManager, constants=constants,
                Experiment=experiment.Experiment, ExperimentCondition=experiment.ExperimentCondition,
                Measurement=experiment.Measurement, Specification=specification.Specification,
                PropertyofInterest=properties.PropertyofInterest, InfluenceFactor=properties.InfluenceFactor,
                ModelStructure=model_structure.ModelStructure, Inport=model_structure.Inport,
                Outport=model_structure.Outport, Monitor=monitors.Monitor,
            )
            logging.getLogger(ValidityFrame.__name__).addHandler(LOG)
        except Exception as exc:  # reported to the user; the app keeps running
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            self.seconds = time.perf_counter() - started
            self._done.set()


class _RecentLog(logging.Handler):
    """Keeps the last messages vfworks logged, for display in the app."""

    def __init__(self, size: int = 500) -> None:
        super().__init__(level=logging.DEBUG)
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
        self.lines: collections.deque[str] = collections.deque(maxlen=size)

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


LOADER = _Loader()
LOG = _RecentLog()


def vfw() -> SimpleNamespace:
    """The vfworks classes; blocks until the background import has finished."""
    return LOADER.wait()


# ------------------------------------------------------------------- catalog
def enums() -> dict[str, dict[str, str]]:
    """Every constants class of the installed vfworks: ``{class: {attribute name: value}}``.

    Enumerated by introspection, so new entries appear without a vfbuilder change.
    Elements store the *values*; the names are shown next to them in dropdowns.
    """
    from vfworks.utils import constants

    return {
        cls_name: {k: v for k, v in vars(cls).items() if not k.startswith("_") and isinstance(v, str)}
        for cls_name, cls in inspect.getmembers(constants, inspect.isclass)
        if cls.__module__ == constants.__name__
    }


def enum_name(enum_class: str, value: str) -> str | None:
    """Attribute name of a constant value, e.g. ``("PropertyType", "property_min") -> "PROPERTY_MIN"``."""
    return next((k for k, v in enums().get(enum_class, {}).items() if v == value), None)


_value_fields: dict[str, tuple[str, ...]] = {}


def spec_value_fields(spec_type: str) -> tuple[str, ...]:
    """Keyword arguments ``Specification(type=spec_type, ...)`` requires, found by asking vfworks.

    vfworks raises ``KeyError`` for each missing one, so the specification is built with
    an empty set and every missing name is added until construction succeeds.
    """
    if spec_type not in _value_fields:
        from vfworks.metamodels.specification import Specification

        fields: dict[str, float] = {}
        for _ in range(20):
            try:
                Specification(name="probe", description="probe", feature="probe", type=spec_type, **fields)
                break
            except KeyError as exc:
                fields[str(exc.args[0])] = 1
        _value_fields[spec_type] = tuple(fields)
    return _value_fields[spec_type]


def builtin_model_types() -> list[str]:
    """Model types ModelLoader.loadModel handles itself; anything else is a Resources/loaders/<type>.py.

    They are hard-coded in an if/elif chain, and importing that module costs as much as
    vfworks itself, so the names are read from its source text.
    """
    try:
        from importlib.util import find_spec

        source = Path(find_spec("vfworks.utils.model.modelLoader").origin).read_text(encoding="utf-8")
        found = re.findall(r"""\btype\s*==\s*["']([^"']+)["']""", source)
    except Exception:
        found = []
    return list(dict.fromkeys(found)) or ["pycaret", "YOLO", "torch"]


def is_package_dir(path: Path) -> bool:
    from vfworks.package.PackageManager import PackageManager

    return PackageManager(packageName=path.name, packageLocation=path.parent).check(path)


# ------------------------------------------------------- frame construction
_construct_lock = threading.Lock()


def construct_frame(build: Callable[[SimpleNamespace], object]):
    """Build a ValidityFrame so it does not share state with frames built before it.

    ``Operational.__init__`` in vfworks uses mutable default arguments, so every frame
    in a process appends its model structures and monitors to the same three lists,
    and a frame loaded later also sees the earlier frame's elements. The shared
    default lists are emptied before construction and the new frame gets lists of its
    own afterwards. (Workaround for a vfworks bug; vfworks itself is not changed.)
    """
    m = vfw()
    defaults = [d for d in m.Operational.__init__.__defaults__ if isinstance(d, list)]
    with _construct_lock:
        for d in defaults:
            d.clear()
        vf = build(m)
        operational = vf._operational
        operational.modelStructures = list(operational.modelStructures)
        vf.runtime_monitors = list(vf.runtime_monitors)
        vf.design_time_monitors = list(vf.design_time_monitors)
        for d in defaults:
            d.clear()
    return vf
