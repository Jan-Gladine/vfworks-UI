"""A live vfworks ValidityFrame being edited.

The vfworks objects are the model: creating, opening and saving a frame are
``ValidityFrame(...)``, ``ValidityFrame(loadExistingVF=True)`` and ``export()``/``zip()``,
and elements are added with vfworks' own ``add*`` methods. This module only adds what
vfworks lacks for an editor: finding elements by GUID, removing them, and the edits
vfworks' setters cannot do (a specification's type or a monitor's observed
specifications are fixed when the object is built, so those objects are rebuilt with
the same GUID and swapped in).

Links are vfworks' own: a property's ``satisfies`` (spec GUIDs), a port's ``mapping``
and a measurement's ``poi`` (property GUIDs), a monitor's ``observes`` (spec objects).
"""
from __future__ import annotations

import json
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from vfbuilder import vfw

VF_EXTENSION = ".vf"
CUSTOM = "property_custom"  # PropertyType.PROPERTY_CUSTOM
DESIGN_TIME = ("DataValidationTime", "ModelValidationTime")  # MonitorTime values filed as design-time
RUN_TIME = ("RunTime",)
INVALID_NAME_CHARS = '\\/:*?"<>|'


class FrameError(Exception):
    pass


@dataclass(frozen=True)
class Reference:
    """``owner`` links to an element through ``relation``."""

    owner_guid: str
    owner_kind: str
    owner_name: str
    relation: str

    def __str__(self) -> str:
        return f"{self.owner_kind} '{self.owner_name}' ({self.relation})"


def custom_code_file(monitor) -> str | None:
    # vfworks keeps it in a private attribute without a property
    return getattr(monitor, "_custom_code_file", None) or None


class FrameSession:
    def __init__(self, vf, source: Path, archive: bool) -> None:
        self.vf = vf
        self.source = source  # the package directory or .vf archive that was opened or created
        self.archive = archive
        self.dirty = False
        self.closed = False

    # ------------------------------------------------------------ lifecycle
    @classmethod
    def new(cls, directory: str | Path, package_name: str, name: str = "", description: str = "") -> FrameSession:
        """Create a new package with ``ValidityFrame(...)``; vfworks writes it to disk right away."""
        package_name = package_name.strip()
        if not package_name or package_name in (".", "..") or any(c in package_name for c in INVALID_NAME_CHARS):
            raise FrameError("The package name must be a plain folder name")
        if package_name.lower().endswith(VF_EXTENSION):
            raise FrameError("Leave '.vf' off the package name; use 'Save as .vf archive' afterwards")
        directory = Path(directory).resolve()
        target = directory / package_name
        if target.exists() and (not target.is_dir() or any(target.iterdir())):
            raise FrameError(f"{target} already exists; open it instead")
        directory.mkdir(parents=True, exist_ok=True)
        vf = vfw.construct_frame(lambda m: m.ValidityFrame(
            name=name or package_name, description=description, VFPackage=package_name, location=str(directory)))
        return cls(vf, target, archive=False)

    @classmethod
    def open(cls, path: str | Path) -> FrameSession:
        """Load a package directory or ``.vf`` archive with ``ValidityFrame(loadExistingVF=True)``."""
        path = Path(path).resolve()
        archive = path.is_file() and path.suffix.lower() == VF_EXTENSION
        if archive:
            _check_archive_layout(path)
        else:
            if not path.is_dir():
                raise FrameError(f"{path} is neither a package directory nor a {VF_EXTENSION} archive")
            if not vfw.is_package_dir(path):
                raise FrameError(f"{path} is not a validity frame package (validity_frame.ini or package folders missing)")
        # vfworks does not store the frame's name; the package name is the best stand-in
        vf = vfw.construct_frame(lambda m: m.ValidityFrame(
            name=path.stem if archive else path.name, loadExistingVF=True,
            VFPackage=str(path) if archive else path.name, location=str(path.parent)))
        session = cls(vf, path, archive)
        session._repair_after_load()
        return session

    def save(self) -> Path:
        """``VF.export()``: writes the package's JSON files (and re-zips an archive)."""
        self.vf.export()
        self.dirty = False
        return self.source

    def save_archive(self) -> Path:
        """``VF.zip()``: export, then write ``<package>.vf`` next to the package directory."""
        archive = Path(self.vf.zip())
        self.dirty = False
        return archive

    def close(self) -> None:
        """``VF.close()``: releases the log file and an archive's temporary working copy."""
        if not self.closed:
            self.vf.close()
            self.closed = True

    def _repair_after_load(self) -> None:
        """Undo two vfworks reload bugs that would break editing.

        - Every condition comes back with its experiment's GUID; the stored GUIDs are
          read from Experiments.json (fresh ones if that fails), so GUIDs stay unique.
        - Specifications come back with ``evaluationType`` None, so monitors built later
          do not see custom specifications; they are rebuilt with vfworks' constructor.
        """
        try:
            stored = json.loads((self.package_root / "Experiments" / "Experiments.json").read_text(encoding="utf-8"))
            stored = {e.get("_GUID"): e.get("_conditions", []) for e in stored.get("_experiments", [])}
        except (OSError, ValueError, AttributeError):
            stored = {}
        seen: set[str] = {e.GUID for _, e, _ in self.iter_elements() if not _is_condition(e)}
        for exp in self.experiments:
            for i, cond in enumerate(exp.conditions):
                raw = stored.get(exp.GUID, [])
                raw = raw[i] if i < len(raw) else {}
                guid = raw.get("_GUID")
                if not guid or guid in seen:
                    guid = str(uuid.uuid4())
                cond.GUID = guid
                cond.timestamp = raw.get("_timestamp", cond.timestamp)
                seen.add(guid)

        for spec in list(self.specifications):
            if spec.evaluationType is None and spec.type in vfw.enums()["PropertyType"].values():
                self._replace_specification(spec, self._build_specification(spec, spec.type, self.spec_values(spec)),
                                            rebuild_monitors=False)

    # ------------------------------------------------------------ structure
    @property
    def package_root(self) -> Path:
        """The directory vfworks works in (for an archive: its temporary unzipped copy)."""
        return Path(self.vf.package_manager.package_root)

    @property
    def package_name(self) -> str:
        return self.source.stem if self.archive else self.source.name

    @property
    def experiments(self) -> list:
        return self.vf.experiments

    @property
    def specifications(self) -> list:
        return self.vf.specifications

    @property
    def properties(self) -> list:
        return self.vf.properties

    @property
    def model_structures(self) -> list:
        return self.vf.modelStructures

    @property
    def monitors(self) -> list:
        return [*self.vf.design_time_monitors, *self.vf.runtime_monitors]

    def iter_elements(self) -> Iterator[tuple[str, object, object | None]]:
        """``(kind, element, parent)`` for every element, nested ones included."""
        for exp in self.experiments:
            yield "experiment", exp, None
            for cond in exp.conditions:
                yield "condition", cond, exp
            for meas in exp.measurements:
                yield "measurement", meas, exp
        for spec in self.specifications:
            yield "specification", spec, None
        for prop in self.properties:
            yield "property", prop, None
        for ms in self.model_structures:
            yield "model structure", ms, None
            for port in ms.inports:
                yield "inport", port, ms
            for port in ms.outports:
                yield "outport", port, ms
        for mon in self.monitors:
            yield "monitor", mon, None

    def find(self, guid: str | None):
        if guid is None:
            return None
        return next((e for _, e, _ in self.iter_elements() if e.GUID == guid), None)

    def kind(self, element) -> str:
        return next((k for k, e, _ in self.iter_elements() if e is element), "element")

    def parent(self, element):
        return next((p for _, e, p in self.iter_elements() if e is element), None)

    def is_influence_factor(self, prop) -> bool:
        return isinstance(prop, vfw.vfw().InfluenceFactor)

    def spec_values(self, spec) -> dict[str, float]:
        """The numbers of a specification's value object, by Specification kwarg name."""
        value = getattr(spec, "_value", None)
        return {f: getattr(value, f"_{f}", None) for f in vfw.spec_value_fields(spec.type)} if value else {}

    def satisfied_by(self, spec) -> list:
        return [p for p in self.properties if spec.GUID in (p.satisfies or [])]

    def observed_by(self, spec) -> list:
        return [m for m in self.monitors if any(s is spec for s in m.observes or [])]

    def references_to(self, element) -> list[Reference]:
        guid = element.GUID
        refs: list[Reference] = []
        for prop in self.properties:
            if guid in (prop.satisfies or []):
                refs.append(Reference(prop.GUID, "property", prop.name, "satisfies"))
        for mon in self.monitors:
            if any(s is element for s in mon.observes or []):
                refs.append(Reference(mon.GUID, "monitor", mon.name, "observes"))
        for ms in self.model_structures:
            for kind, ports in (("inport", ms.inports), ("outport", ms.outports)):
                for port in ports:
                    if port.mapping == guid:
                        refs.append(Reference(port.GUID, kind, f"{ms.name}.{port.name}", "mapped to"))
        for exp in self.experiments:
            for meas in exp.measurements:
                if meas.poi == guid:
                    refs.append(Reference(meas.GUID, "measurement", f"{exp.name}.{meas.name}", "measures"))
        return refs

    def _changed(self):
        self.dirty = True

    # ------------------------------------------------------------------ add
    def add_experiment(self, name: str = "", label: str = "nominal"):
        exp = vfw.vfw().Experiment(name=name, description="", label=label)
        self.vf.addExperiment(exp)
        self._changed()
        return exp

    def add_condition(self, exp, name: str = "", value=""):
        cond = vfw.vfw().ExperimentCondition(name=name, description="", value=value)
        exp.addCondition(cond)
        self._changed()
        return cond

    def add_measurement(self, exp, name: str = "", reference: str | None = None):
        meas = vfw.vfw().Measurement(name=name, description="", dataPoints=[], reference=reference)
        exp.addMeasurement(meas)
        self._changed()
        return meas

    def add_specification(self, name: str = "", feature: str = "", spec_type: str = "property_min",
                          values: dict | None = None, description: str = ""):
        spec = vfw.vfw().Specification(name=name, description=description, feature=feature, type=spec_type,
                                       **self._complete_values(spec_type, values or {}))
        self.vf.addSpecification(spec)
        self._changed()
        return spec

    def add_property(self, name: str = "", influence_factor: bool = False, description: str = ""):
        m = vfw.vfw()
        prop = (m.InfluenceFactor if influence_factor else m.PropertyofInterest)(name=name, description=description)
        self.vf.addProperty(prop)
        self._changed()
        return prop

    def add_model_structure(self, name: str = ""):
        ms = vfw.vfw().ModelStructure(name=name, description="", inports=[], outports=[])
        self.vf.addModelStructure(ms)
        self._changed()
        return ms

    def add_port(self, ms, direction: str, name: str = ""):
        m = vfw.vfw()
        if direction == "in":
            port = m.Inport(name=name, description="")
            ms.add_inport(port)
        else:
            port = m.Outport(name=name, description="")
            ms.add_outport(port)
        self._changed()
        return port

    def add_monitor(self, name: str = "", monitor_time: str = "RunTime", observes: list[str] | None = None,
                    code_file: str | None = None, description: str = ""):
        mon = vfw.vfw().Monitor(name=name, description=description, monitor_time=monitor_time,
                                observes=self._specs(observes or []), custom_code_file=code_file or None)
        self._file_monitor(mon)
        self._changed()
        return mon

    # --------------------------------------------------------------- update
    def set(self, element, attr: str, value) -> None:
        """Set a plain attribute through vfworks' property setter."""
        setattr(element, attr, value)
        if attr == "description" and getattr(element, "type", None) == CUSTOM and self._is_spec(element):
            # a custom specification's value is its description, copied at construction
            self._refresh_value(element)
        self._changed()

    def set_feature(self, spec, feature: str) -> None:
        """Monitors key their per-spec state by feature; re-key it the way Monitor() initialises it.

        (Not a full monitor rebuild: that would re-run the monitor's custom code on every keystroke.)
        """
        spec.feature = feature
        unknown = vfw.vfw().constants.StatusType.UNKNOWN
        for mon in self.observed_by(spec):
            mon.spec_status = {s.feature: unknown for s in mon.observes}
            mon.last_observed_values = {s.feature: 0.0 for s in mon.observes}
        self._changed()

    def set_spec_type(self, spec, spec_type: str):
        """A specification's evaluation type is fixed at construction: rebuild it, keeping its GUID."""
        new = self._build_specification(spec, spec_type, self.spec_values(spec))
        self._replace_specification(spec, new)
        self._changed()
        return new

    def set_spec_value(self, spec, field: str, number) -> None:
        values = self.spec_values(spec)
        values[field] = number
        self._refresh_value(spec, values)
        self._changed()

    def set_property_kind(self, prop, influence_factor: bool):
        """Property of interest <-> influence factor is a different vfworks class: rebuild it."""
        if self.is_influence_factor(prop) == influence_factor:
            return prop
        m = vfw.vfw()
        cls = m.InfluenceFactor if influence_factor else m.PropertyofInterest
        new = cls(name=prop.name, description=prop.description, domain=prop.domain, unit=prop.unit,
                  datatype=prop.datatype, min=prop.min, max=prop.max)
        new.satisfies = list(prop.satisfies or [])
        _keep_identity(new, prop)
        index = next(i for i, p in enumerate(self.properties) if p is prop)
        self.properties[index] = new
        self._changed()
        return new

    def set_satisfies(self, prop, spec_guids: list[str]) -> None:
        prop.satisfies = [g for g in spec_guids if self._is_spec(self.find(g))]
        self._changed()

    def set_satisfied_by(self, spec, prop_guids: list[str]) -> None:
        wanted = set(prop_guids)
        for prop in self.properties:
            has = spec.GUID in (prop.satisfies or [])
            if prop.GUID in wanted and not has:
                prop.satisfies = [*(prop.satisfies or []), spec.GUID]
            elif prop.GUID not in wanted and has:
                prop.satisfies = [g for g in prop.satisfies if g != spec.GUID]
        self._changed()

    def set_mapping(self, port, prop_guid: str | None) -> None:
        prop = self.find(prop_guid)
        if prop is not None:
            port.add_mapping_relation(type="poi", poi=prop)
        else:
            port.mapping = None
        self._changed()

    def set_measured_property(self, meas, prop_guid: str | None) -> None:
        # vf.assign_poi2measurement links every measurement with that name, in all
        # experiments; the measurement's own poi attribute links just this one
        prop = self.find(prop_guid)
        meas.poi = prop.GUID if prop is not None else None
        self._changed()

    def set_observes(self, mon, spec_guids: list[str]):
        new = self._rebuild_monitor(mon, observes=self._specs(spec_guids))
        self._changed()
        return new

    def set_monitor_time(self, mon, monitor_time: str):
        new = self._rebuild_monitor(mon, monitor_time=monitor_time)
        self._changed()
        return new

    def set_code_file(self, mon, code_file: str | None):
        new = self._rebuild_monitor(mon, custom_code_file=code_file or None)
        self._changed()
        return new

    # --------------------------------------------------------------- delete
    def delete(self, element) -> list[Reference]:
        """Remove an element and every link to it. Returns the links removed."""
        refs = self.references_to(element)
        kind, parent = self.kind(element), self.parent(element)
        if kind == "specification":
            self.specifications.remove(element)
            for prop in self.properties:
                if element.GUID in (prop.satisfies or []):
                    prop.satisfies = [g for g in prop.satisfies if g != element.GUID]
            for mon in self.observed_by(element):
                self._rebuild_monitor(mon, observes=[s for s in mon.observes if s is not element])
        elif kind == "property":
            self.properties.remove(element)
            for ms in self.model_structures:
                for port in (*ms.inports, *ms.outports):
                    if port.mapping == element.GUID:
                        port.mapping = None
            for exp in self.experiments:
                for meas in exp.measurements:
                    if meas.poi == element.GUID:
                        meas.poi = None
        elif kind == "monitor":
            self._monitor_list(element).remove(element)
        elif kind == "experiment":
            self.experiments.remove(element)
        elif kind == "condition":
            parent.conditions.remove(element)
        elif kind == "measurement":
            parent.measurements.remove(element)
        elif kind == "model structure":
            self.model_structures.remove(element)
        elif kind == "inport":
            parent.inports.remove(element)
        elif kind == "outport":
            parent.outports.remove(element)
        else:
            raise FrameError(f"Cannot delete {element!r}")
        self._changed()
        return refs

    # ------------------------------------------------------------- internals
    def _is_spec(self, element) -> bool:
        return element is not None and any(element is s for s in self.specifications)

    def _specs(self, guids: list[str]) -> list:
        by_guid = {s.GUID: s for s in self.specifications}
        return [by_guid[g] for g in guids if g in by_guid]

    def _complete_values(self, spec_type: str, values: dict) -> dict:
        """All kwargs the type needs; a missing one would make vfworks raise KeyError."""
        fields = vfw.spec_value_fields(spec_type)
        defaults = {"granularity": 10}  # ValueRange's own default
        return {f: values[f] if values.get(f) is not None else defaults.get(f, 0) for f in fields}

    def _build_specification(self, spec, spec_type: str, values: dict):
        new = vfw.vfw().Specification(name=spec.name, description=spec.description, feature=spec.feature,
                                      type=spec_type, **self._complete_values(spec_type, values))
        _keep_identity(new, spec)
        old_value = getattr(spec, "_value", None)
        if old_value is not None:
            _keep_identity(new.value, old_value)
        return new

    def _refresh_value(self, spec, values: dict | None = None) -> None:
        """Replace a specification's value object (vfworks builds it only in the constructor)."""
        probe = self._build_specification(spec, spec.type, self.spec_values(spec) if values is None else values)
        spec.value = probe.value

    def _replace_specification(self, old, new, rebuild_monitors: bool = True) -> None:
        index = next(i for i, s in enumerate(self.specifications) if s is old)
        self.specifications[index] = new
        for mon in self.monitors:
            if any(s is old for s in mon.observes or []):
                observes = [new if s is old else s for s in mon.observes]
                if rebuild_monitors:
                    self._rebuild_monitor(mon, observes=observes)
                else:
                    mon.observes = observes

    def _monitor_list(self, mon) -> list:
        for monitors in (self.vf.design_time_monitors, self.vf.runtime_monitors):
            if any(m is mon for m in monitors):
                return monitors
        raise FrameError(f"Monitor {mon.name} is not part of this frame")

    def _file_monitor(self, mon, replace=None) -> None:
        """Add with ``vf.addMonitor`` (files it by monitor time and loads its custom code).

        When replacing a monitor in the same list, it takes the old one's place instead.
        """
        if replace is not None:
            monitors = self._monitor_list(replace)
            same_list = (mon.type in DESIGN_TIME) == (monitors is self.vf.design_time_monitors)
            if same_list:
                mon.packageName = self.vf.package_manager.packageName
                mon.setup(self.vf.package_manager.package_root)  # what addMonitor does
                monitors[next(i for i, m in enumerate(monitors) if m is replace)] = mon
                return
            monitors.remove(replace)
        before = len(self.monitors)
        self.vf.addMonitor(mon)
        if len(self.monitors) == before:  # addMonitor silently drops unknown monitor times
            raise FrameError(f"vfworks does not file monitor time '{mon.type}'")

    def _rebuild_monitor(self, mon, **changes):
        """Monitors fix their per-feature status and custom-code requirement at construction."""
        args = dict(name=mon.name, description=mon.description, monitor_time=mon.type,
                    observes=list(mon.observes or []), custom_code_file=custom_code_file(mon))
        args.update(changes)
        new = vfw.vfw().Monitor(**args)
        _keep_identity(new, mon)
        self._file_monitor(new, replace=mon)
        return new


def _check_archive_layout(archive: Path) -> None:
    """Refuse archives vfworks cannot read, instead of opening them as an empty frame.

    vfworks unzips a .vf and expects ``validity_frame.ini`` and ``Metadata/`` at the top
    of the archive (``VF.zip()`` writes it that way). An archive made by zipping the
    package *folder* has everything one level down; vfworks then only prints
    "Stored metadata cannot be read!" and loads nothing, and saving would write an
    empty frame into the archive.
    """
    try:
        with zipfile.ZipFile(archive) as zf:
            names = [n.rstrip("/") for n in zf.namelist()]
    except zipfile.BadZipFile:
        raise FrameError(f"{archive.name} is not a zip archive") from None
    if "validity_frame.ini" in names:
        return
    nested = sorted({n.split("/")[0] for n in names if n.endswith("/validity_frame.ini") and n.count("/") == 1})
    if nested:
        raise FrameError(
            f"{archive.name} holds the package one folder down ({nested[0]}/validity_frame.ini, "
            f"{nested[0]}/Metadata/...), but vfworks expects those at the top of the archive, so it would "
            f"load an empty frame. The archive was probably made by zipping the package folder. Extract it "
            f"and open the {nested[0]} folder instead; Save as .vf archive then writes a correct archive.")
    raise FrameError(f"{archive.name} is not a validity frame package (no validity_frame.ini in the archive)")


def _keep_identity(new, old) -> None:
    new.GUID = old.GUID
    new.timestamp = old.timestamp


def _is_condition(element) -> bool:
    return type(element).__name__ == "ExperimentCondition"
