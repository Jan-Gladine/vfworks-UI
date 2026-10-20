"""Validator: checks a live frame and returns a list of issues. Does not change anything.

Issues point at elements by their vfworks GUID.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Literal

from vfbuilder import package_files, vfw
from vfbuilder.frame import CUSTOM, DESIGN_TIME, RUN_TIME, FrameSession, custom_code_file

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class Issue:
    severity: Severity
    element_id: str
    message: str


def has_errors(issues: Iterable[Issue]) -> bool:
    return any(i.severity == "error" for i in issues)


def validate(session: FrameSession) -> list[Issue]:
    issues: list[Issue] = []
    enums = vfw.enums()

    def error(element, message: str) -> None:
        issues.append(Issue("error", element.GUID, message))

    def warning(element, message: str) -> None:
        issues.append(Issue("warning", element.GUID, message))

    def check_enum(element, enum_class: str, value, label: str) -> None:
        if value not in enums.get(enum_class, {}).values():
            error(element, f"{label} '{value}' is not a {enum_class} of the installed vfworks")

    def check_unique(elements: Iterable, scope: str) -> None:
        by_name: dict[str, list] = defaultdict(list)
        for element in elements:
            if (element.name or "").strip():
                by_name[element.name.strip()].append(element)
        for name, group in by_name.items():
            if len(group) > 1:
                for element in group:
                    error(element, f"Name '{name}' is used more than once {scope}")

    # ------------------------------------------------------------------- names
    for kind, element, _ in session.iter_elements():
        if not (element.name or "").strip():
            error(element, f"This {kind} needs a name")
    # vfworks keys graph nodes by name across these three types
    check_unique([*session.specifications, *session.properties, *session.monitors],
                 "across specifications, properties and monitors")
    check_unique(session.experiments, "among experiments")
    check_unique(session.model_structures, "among model structures")
    for exp in session.experiments:
        check_unique(exp.conditions, f"among the conditions of experiment '{exp.name}'")
        check_unique(exp.measurements, f"among the measurements of experiment '{exp.name}'")
    for ms in session.model_structures:
        check_unique(ms.inports, f"among the inports of '{ms.name}'")
        check_unique(ms.outports, f"among the outports of '{ms.name}'")

    # ------------------------------------------------------------ measurements
    # vf.assign_poi2measurement (used by scripts) links measurements by name
    same_name = defaultdict(list)
    for exp in session.experiments:
        for meas in exp.measurements:
            if (meas.name or "").strip():
                same_name[meas.name.strip()].append(meas)
    for name, group in same_name.items():
        if len({m.poi for m in group if m.poi}) > 1:
            for meas in group:
                warning(meas, f"Measurements named '{name}' measure different properties; vfworks' "
                              "assign_poi2measurement links by name and cannot tell them apart")
    property_guids = {p.GUID for p in session.properties}
    for exp in session.experiments:
        for meas in exp.measurements:
            if meas.poi and meas.poi not in property_guids:
                error(meas, "Measures a property that does not exist")

    # ---------------------------------------------------------- specifications
    for spec in session.specifications:
        if not (spec.feature or "").strip():
            error(spec, "Feature is required (the data key the specification is evaluated against)")
        check_enum(spec, "PropertyType", spec.type, "Type")
        values = session.spec_values(spec)
        for field, value in values.items():
            if not _is_number(value):
                error(spec, f"{field} must be a number")
        if all(_is_number(v) for v in values.values()):
            if {"valueMin", "valueMax"} <= values.keys() and values["valueMin"] >= values["valueMax"]:
                error(spec, "valueMin must be smaller than valueMax")
            if "granularity" in values and (values["granularity"] != int(values["granularity"])
                                            or values["granularity"] < 1):
                error(spec, "granularity must be a whole number of at least 1 (number of bins)")
            if "deviation" in values and values["deviation"] < 0:
                warning(spec, "deviation is negative, so no value can ever be valid")
        if not session.satisfied_by(spec):
            warning(spec, "Not satisfied by any property")
        if not session.observed_by(spec):
            warning(spec, "Not observed by any monitor")

    # -------------------------------------------------------------- properties
    spec_guids = {s.GUID for s in session.specifications}

    def check_quantity(element) -> None:
        check_enum(element, "DomainType", element.domain, "Domain")
        check_enum(element, "UnitType", element.unit, "Unit")
        check_enum(element, "DataType", element.datatype, "Datatype")
        if _is_number(element.min) and _is_number(element.max) and element.min > element.max:
            warning(element, f"min ({element.min}) is greater than max ({element.max})")

    for prop in session.properties:
        check_quantity(prop)
        if any(g not in spec_guids for g in prop.satisfies or []):
            error(prop, "Satisfies a specification that does not exist")

    # -------------------------------------------------------- model structures
    root = session.package_root
    loaders = package_files.list_loaders(root)
    builtin = vfw.builtin_model_types()
    for ms in session.model_structures:
        for kind, ports in (("inport", ms.inports), ("outport", ms.outports)):
            for port in ports:
                check_quantity(port)
                if not port.mapping:
                    warning(port, f"{kind.capitalize()} is not mapped to a property")
                elif port.mapping not in property_guids:
                    error(port, "Mapped to a property that does not exist")
        if not isinstance(ms.redundancy, int) or ms.redundancy < 1:
            error(ms, "Redundancy must be a whole number of at least 1")
        if not ms.modelType:
            warning(ms, "No model type selected; vfworks cannot load the model")
        elif ms.modelType not in builtin and ms.modelType not in loaders:
            warning(ms, f"Model type '{ms.modelType}' is not built in and "
                        f"Resources/loaders/{ms.modelType}.py does not exist in the package")
        if not ms.modelRef:
            warning(ms, "No model reference set")

    # ---------------------------------------------------------------- monitors
    monitor_files = package_files.list_monitor_files(root)
    for mon in session.monitors:
        if mon.type not in (*DESIGN_TIME, *RUN_TIME):
            error(mon, f"Monitor time '{mon.type}' is not one vfworks files")
        observed = list(mon.observes or [])
        if not observed:
            error(mon, "A monitor must observe at least one specification")
        custom = [s.name for s in observed if s.type == CUSTOM]
        code = custom_code_file(mon)
        if custom and not code:
            error(mon, f"Observes custom specification(s) {', '.join(custom)} and needs a custom code file")
        if code and code not in monitor_files:
            warning(mon, f"Custom code file '{code}' does not exist in the package's Resources/monitors")
        by_feature = defaultdict(list)
        for spec in observed:
            if (spec.feature or "").strip():
                by_feature[spec.feature.strip()].append(spec.name)
        for feature, names in by_feature.items():
            if len(names) > 1:
                warning(mon, f"Observed specifications {', '.join(names)} share feature '{feature}'; "
                             "their status in this monitor will collide")
    return issues


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
