"""Edit forms for each element type, working on the live vfworks objects.

Plain attributes are written through vfworks' property setters (``session.set``);
links and the edits that need an object rebuilt go through the FrameSession methods.
Because a rebuild swaps in a new object with the same GUID, forms always find
elements by GUID, and a rebuild re-renders the form. References are chosen from
pickers keyed by GUID.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from nicegui import ui

from vfbuilder import package_files, vfw
from vfbuilder.frame import CUSTOM, custom_code_file
from vfbuilder.ui.filebrowser import browse

if TYPE_CHECKING:
    from vfbuilder.ui.builder import Builder

VALUE_LABELS = {
    "valueMin": "Minimum (valueMin)",
    "valueMax": "Maximum (valueMax)",
    "granularity": "Granularity (number of bins)",
    "average": "Average",
    "deviation": "Deviation (+/-)",
}
KIND_LABELS = {False: "Property of interest", True: "Influence factor"}


# ----------------------------------------------------------------- basic widgets
def display_name(element) -> str:
    return (getattr(element, "name", "") or "").strip() or "(unnamed)"


def text(b: Builder, label: str, element, attr: str, **kwargs) -> ui.input:
    def on_change(e) -> None:
        b.session.set(element, attr, e.value or "")
        b.changed()

    return ui.input(label, value=str(getattr(element, attr) or ""), on_change=on_change, **kwargs).classes("w-full")


def description(b: Builder, element) -> None:
    def on_change(e) -> None:
        b.session.set(element, "description", e.value or "")
        b.changed()

    ui.textarea("Description", value=element.description or "", on_change=on_change).props(
        "autogrow rows=1").classes("w-full")


def as_number(value):
    """ui.number yields floats; keep whole numbers as ints so 100 is not exported as 100.0."""
    if value is None or value == "":
        return None
    value = float(value)
    return int(value) if value.is_integer() else value


def number(label: str, value, on_value: Callable, *, default=0) -> ui.number:
    def on_change(e) -> None:
        new = as_number(e.value)
        on_value(default if new is None else new)

    return ui.number(label, value=value, on_change=on_change).classes("grow")


def enum_options(b: Builder, enum_class: str, current=None) -> dict[str, str]:
    """Dropdown options over a vfworks constants class: value -> 'NAME (value)'."""
    options = {v: f"{k}  ({v})" for k, v in b.state.enums.get(enum_class, {}).items()}
    if current is not None and current not in options:
        options[current] = f"{current}  (not in the installed vfworks)"
    return options


def enum_select(b: Builder, label: str, enum_class: str, element, attr: str) -> ui.select:
    current = getattr(element, attr)

    def on_change(e) -> None:
        b.session.set(element, attr, e.value)
        b.changed()

    return ui.select(enum_options(b, enum_class, current), label=label, value=current,
                     on_change=on_change).classes("grow min-w-[10rem]")


def picker(label: str, options: dict[str, str], value, on_change: Callable, *, multiple: bool = False,
           on_new: Callable[[], None] | None = None, new_label: str = "Create new...") -> ui.select:
    """Pick existing elements by name (stored by GUID), with an inline "create new" button."""
    if multiple:
        value = [v for v in value if v in options]
    elif value not in options:
        value = None
    with ui.row().classes("w-full items-center no-wrap gap-1"):
        select = ui.select(options, label=label, value=value, multiple=multiple, with_input=True,
                           clearable=not multiple, on_change=lambda e: on_change(e.value)).classes("grow")
        if multiple:
            select.props("use-chips")
        if on_new is not None:
            ui.button(new_label, icon="add", on_click=on_new).props("flat dense no-caps")
    return select


def options_of(elements: list) -> dict[str, str]:
    return {e.GUID: display_name(e) for e in elements}


def heading(text_: str) -> None:
    ui.label(text_).classes("text-sm font-medium text-gray-600 mt-3")


def parse_scalar(raw: str | None):
    """Condition values are free-form: keep numbers as numbers, everything else as text."""
    raw = (raw or "").strip()
    for convert in (int, float):
        try:
            return convert(raw)
        except ValueError:
            pass
    return raw


def slug(name: str, fallback: str) -> str:
    return re.sub(r"\W+", "_", name or "").strip("_") or fallback


# --------------------------------------------------------------- create dialogs
def create_dialog(b: Builder, kind: str, link: Callable[[object], None] | None = None) -> None:
    """Small dialog that creates a specification, property or monitor through vfworks, then links it."""
    values: dict = {"name": "", "description": ""}
    session = b.session
    with ui.dialog().props("persistent") as dialog, ui.card().classes("w-[34rem] max-w-full"):
        ui.label(f"New {kind}").classes("text-lg font-medium")
        ui.input("Name", on_change=lambda e: values.__setitem__("name", e.value or "")).classes("w-full")
        ui.textarea("Description", on_change=lambda e: values.__setitem__("description", e.value or "")).props(
            "autogrow rows=1").classes("w-full")
        if kind == "specification":
            values.update(feature="", type="property_min", values={})
            ui.input("Feature", autocomplete=b.state.feature_suggestions(),
                     on_change=lambda e: values.__setitem__("feature", e.value or "")).classes("w-full")

            @ui.refreshable
            def value_fields() -> None:
                with ui.row().classes("w-full gap-2"):
                    for field in vfw.spec_value_fields(values["type"]):
                        number(VALUE_LABELS.get(field, field), values["values"].get(field),
                               lambda v, f=field: values["values"].__setitem__(f, v))

            def set_type(e) -> None:
                values["type"] = e.value
                value_fields.refresh()

            ui.select(enum_options(b, "PropertyType"), label="Type", value=values["type"],
                      on_change=set_type).classes("w-full")
            value_fields()
        elif kind == "property":
            values["influence_factor"] = False
            ui.toggle(KIND_LABELS, value=False,
                      on_change=lambda e: values.__setitem__("influence_factor", e.value)).props("no-caps")
        elif kind == "monitor":
            values["time"] = "RunTime"
            ui.select(enum_options(b, "MonitorTime"), label="Monitor time", value="RunTime",
                      on_change=lambda e: values.__setitem__("time", e.value)).classes("w-full")

        def create() -> None:
            if not values["name"].strip():
                ui.notify("Give it a name first", type="warning")
                return
            if kind == "specification":
                element = session.add_specification(values["name"], values["feature"], values["type"],
                                                    values["values"], description=values["description"])
            elif kind == "property":
                element = session.add_property(values["name"], values["influence_factor"],
                                               description=values["description"])
            else:
                element = session.add_monitor(values["name"], values["time"], description=values["description"])
            if link is not None:
                link(element)
            dialog.close()
            b.changed(structural=True)
            ui.notify(f"Created {kind} '{element.name}'" + (" and linked it" if link else ""), type="positive")

        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            ui.button("Create and link" if link else "Create", on_click=create)
    dialog.open()


# -------------------------------------------------------------------- experiments
def experiment_form(b: Builder, exp) -> None:
    s = b.session
    text(b, "Name", exp, "name")
    description(b, exp)
    text(b, "Label", exp, "label")

    heading("Conditions")
    for cond in exp.conditions:
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            text(b, "Name", cond, "name")

            def set_value(e, cond=cond) -> None:
                s.set(cond, "value", parse_scalar(e.value))
                b.changed()

            ui.input("Value", value=str(cond.value), on_change=set_value).classes("w-full")
            ui.button(icon="delete", on_click=lambda c=cond: b.confirm_delete(c)).props("flat round dense")

    def add_condition() -> None:
        s.add_condition(exp)
        b.changed(structural=True)

    ui.button("Add condition", icon="add", on_click=add_condition).props("flat dense no-caps")

    heading("Measurements")
    for meas in exp.measurements:
        with ui.card().props("flat bordered").classes("w-full gap-1"):
            with ui.row().classes("w-full items-center no-wrap gap-2"):
                text(b, "Name", meas, "name")
                text(b, "Reference (data file)", meas, "reference")
                ui.button(icon="delete", on_click=lambda m=meas: b.confirm_delete(m)).props("flat round dense")

            def set_property(guid, meas=meas) -> None:
                s.set_measured_property(meas, guid)
                b.changed()

            def new_property(meas=meas) -> None:
                create_dialog(b, "property", lambda prop: s.set_measured_property(meas, prop.GUID))

            picker("Measures property", options_of(s.properties), meas.poi, set_property,
                   on_new=new_property, new_label="New property...")

    def add_measurement() -> None:
        s.add_measurement(exp)
        b.changed(structural=True)

    ui.button("Add measurement", icon="add", on_click=add_measurement).props("flat dense no-caps")


# ----------------------------------------------------------------- specifications
def specification_form(b: Builder, spec) -> None:
    s = b.session
    text(b, "Name", spec, "name")
    description(b, spec)

    def set_feature(e) -> None:
        s.set_feature(spec, e.value or "")
        b.changed()

    ui.input("Feature (data key the specification is evaluated against)", value=spec.feature or "",
             autocomplete=b.state.feature_suggestions(exclude=spec), on_change=set_feature).classes("w-full")

    def set_type(e) -> None:
        s.set_spec_type(spec, e.value)  # rebuilt with the same GUID
        b.changed(structural=True)

    ui.select(enum_options(b, "PropertyType", spec.type), label="Type", value=spec.type,
              on_change=set_type).classes("w-full")
    fields = vfw.spec_value_fields(spec.type)
    if spec.type == CUSTOM:
        ui.label("A custom specification has no values; its description is used as the value "
                 "and a monitor's custom code decides validity.").classes("text-sm text-gray-600")
    elif fields:
        values = s.spec_values(spec)
        with ui.row().classes("w-full gap-2"):
            for field in fields:
                def set_value(v, field=field) -> None:
                    s.set_spec_value(spec, field, v)
                    b.changed()

                number(VALUE_LABELS.get(field, field), values.get(field), set_value)

    heading("Links")

    def set_satisfied_by(guids) -> None:
        s.set_satisfied_by(spec, guids or [])
        b.changed()

    picker("Satisfied by (properties)", options_of(s.properties), [p.GUID for p in s.satisfied_by(spec)],
           set_satisfied_by, multiple=True, new_label="New property...",
           on_new=lambda: create_dialog(b, "property", lambda prop: s.set_satisfies(prop, [spec.GUID])))

    with ui.row().classes("w-full items-center gap-1"):
        ui.label("Observed by:").classes("text-sm text-gray-600")
        monitors = s.observed_by(spec)
        for mon in monitors:
            ui.chip(display_name(mon), icon="monitor_heart", on_click=lambda m=mon: b.open_element(m.GUID)).props(
                "outline clickable")
        if not monitors:
            ui.label("no monitor").classes("text-sm")
        ui.space()
        ui.button("New monitor...", icon="add", on_click=lambda: create_dialog(
            b, "monitor", lambda mon: s.set_observes(mon, [spec.GUID]))).props("flat dense no-caps")
    ui.label("Edit which specifications a monitor observes on the monitor itself.").classes("text-xs text-gray-500")


# --------------------------------------------------------------------- properties
def _quantity_fields(b: Builder, element) -> None:
    """Domain, unit, datatype and range: shared by properties and ports."""
    s = b.session
    with ui.row().classes("w-full gap-2"):
        enum_select(b, "Domain", "DomainType", element, "domain")
        enum_select(b, "Unit", "UnitType", element, "unit")
        enum_select(b, "Datatype", "DataType", element, "datatype")
    with ui.row().classes("w-full gap-2"):
        for attr in ("min", "max"):
            def set_number(v, attr=attr) -> None:
                s.set(element, attr, v)
                b.changed()

            number(attr.capitalize(), getattr(element, attr), set_number)


def property_form(b: Builder, prop) -> None:
    s = b.session
    text(b, "Name", prop, "name")
    description(b, prop)

    def set_kind(e) -> None:
        s.set_property_kind(prop, bool(e.value))  # a different vfworks class, same GUID
        b.changed(structural=True)

    ui.toggle(KIND_LABELS, value=s.is_influence_factor(prop), on_change=set_kind).props("no-caps")
    _quantity_fields(b, prop)

    heading("Links")

    def set_satisfies(guids) -> None:
        s.set_satisfies(prop, list(guids or []))
        b.changed()

    picker("Satisfies (specifications)", options_of(s.specifications), list(prop.satisfies or []), set_satisfies,
           multiple=True, new_label="New specification...",
           on_new=lambda: create_dialog(b, "specification",
                                        lambda spec: s.set_satisfies(prop, [*(prop.satisfies or []), spec.GUID])))

    users = [r for r in s.references_to(prop) if r.relation != "satisfies"]
    with ui.row().classes("w-full items-center gap-1"):
        ui.label("Used by:").classes("text-sm text-gray-600")
        for ref in users:
            ui.chip(f"{ref.owner_kind} {ref.owner_name}", on_click=lambda r=ref: b.open_element(r.owner_guid)).props(
                "outline clickable")
        if not users:
            ui.label("no port or measurement").classes("text-sm")


# --------------------------------------------------------------- model structures
def structure_form(b: Builder, ms) -> None:
    s = b.session
    root = s.package_root
    text(b, "Name", ms, "name")
    description(b, ms)

    builtin = b.state.builtin_model_types
    options = {t: f"{t}  (built in)" for t in builtin}
    options.update({t: f"{t}  (Resources/loaders/{t}.py)" for t in package_files.list_loaders(root) if t not in builtin})
    if ms.modelType and ms.modelType not in options:
        options[ms.modelType] = f"{ms.modelType}  (no such loader in the package)"

    def set_type(e) -> None:
        s.set(ms, "modelType", e.value or None)
        b.changed()

    async def new_loader() -> None:
        name = await b.ask_text("New model loader", "Model type (file name without .py)",
                                slug(ms.name, "my_model") + "_loader")
        if not name:
            return
        try:
            created = package_files.create_loader_file(root, name)
        except package_files.PackageFileError as exc:
            ui.notify(str(exc), type="negative")
            return
        s.set(ms, "modelType", created.stem)
        ui.notify(f"Created {created}; implement load_model() in it.", type="positive")
        b.changed(structural=True)

    with ui.row().classes("w-full items-center no-wrap gap-1"):
        ui.select(options, label="Model type (loader)", value=ms.modelType or None, clearable=True,
                  on_change=set_type).classes("grow")
        ui.button("New loader...", icon="add", on_click=new_loader).props("flat dense no-caps")

    async def browse_ref() -> None:
        start = root / "Sources" if (root / "Sources").is_dir() else root
        path = await browse("Model file or folder", start, mode="any")
        if path is None:
            return
        s.set(ms, "modelRef", _package_relative(path, root))
        b.changed(structural=True)

    with ui.row().classes("w-full items-center no-wrap gap-1"):
        text(b, "Model reference (file or folder)", ms, "modelRef")
        ui.button("Browse...", icon="folder_open", on_click=browse_ref).props("flat dense no-caps")
    ui.label("Relative references are resolved inside the package, by default under Sources/.").classes(
        "text-xs text-gray-500")

    def set_redundancy(value) -> None:
        s.set(ms, "redundancy", max(1, int(value)))
        b.changed()

    with ui.row().classes("w-48"):
        number("Redundancy", ms.redundancy, set_redundancy, default=1).props("min=1 step=1")

    for title, direction, ports in (("Inports", "in", ms.inports), ("Outports", "out", ms.outports)):
        heading(title)
        for port in ports:
            with ui.card().props("flat bordered").classes("w-full gap-1"):
                with ui.row().classes("w-full items-center no-wrap gap-2"):
                    text(b, "Name", port, "name")
                    text(b, "Description", port, "description")
                    ui.button(icon="delete", on_click=lambda p=port: b.confirm_delete(p)).props("flat round dense")
                _quantity_fields(b, port)

                def set_mapping(guid, port=port) -> None:
                    s.set_mapping(port, guid)
                    b.changed()

                def new_property(port=port) -> None:
                    create_dialog(b, "property", lambda prop: s.set_mapping(port, prop.GUID))

                picker("Mapped to property", options_of(s.properties), port.mapping, set_mapping,
                       on_new=new_property, new_label="New property...")

        def add_port(direction=direction) -> None:
            s.add_port(ms, direction)
            b.changed(structural=True)

        ui.button(f"Add {direction}port", icon="add", on_click=add_port).props("flat dense no-caps")


def _package_relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


# ----------------------------------------------------------------------- monitors
def monitor_form(b: Builder, mon) -> None:
    s = b.session
    text(b, "Name", mon, "name")
    description(b, mon)

    def set_time(e) -> None:
        s.set_monitor_time(mon, e.value)  # rebuilt; vfworks files it as design-time or runtime
        b.changed(structural=True)

    ui.select(enum_options(b, "MonitorTime", mon.type), label="Monitor time", value=mon.type,
              on_change=set_time).classes("w-full")

    heading("Links")

    def set_observes(guids) -> None:
        s.set_observes(mon, list(guids or []))
        b.changed(structural=True)

    picker("Observes (specifications, at least one)", options_of(s.specifications),
           [sp.GUID for sp in mon.observes or []], set_observes, multiple=True, new_label="New specification...",
           on_new=lambda: create_dialog(b, "specification", lambda spec: s.set_observes(
               mon, [*(sp.GUID for sp in mon.observes or []), spec.GUID])))

    root = s.package_root
    files = package_files.list_monitor_files(root)
    current = custom_code_file(mon)
    if current and current not in files:
        files = [*files, current]

    def set_file(e) -> None:
        s.set_code_file(mon, e.value or None)  # rebuilt; vfworks loads the file
        b.changed(structural=True)

    async def new_file() -> None:
        name = await b.ask_text("New monitor code file", "File name", slug(mon.name, "monitor") + ".py")
        if not name:
            return
        try:
            created = package_files.create_monitor_file(root, name)
        except package_files.PackageFileError as exc:
            ui.notify(str(exc), type="negative")
            return
        s.set_code_file(mon, created.name)
        ui.notify(f"Created {created}; implement validate() in it.", type="positive")
        b.changed(structural=True)

    with ui.row().classes("w-full items-center no-wrap gap-1"):
        ui.select(files, label="Custom code file (Resources/monitors)", value=current, clearable=True,
                  on_change=set_file).classes("grow")
        ui.button("Create from template...", icon="add", on_click=new_file).props("flat dense no-caps")
    custom = [display_name(sp) for sp in mon.observes or [] if sp.type == CUSTOM]
    if custom:
        ui.label(f"Required: {', '.join(custom)} is a custom specification. The file must define "
                 "validate(monitor=None, **kwargs) returning {feature: bool}.").classes("text-xs text-gray-600")
    else:
        ui.label("Optional: only needed to override the built-in checks.").classes("text-xs text-gray-500")


# ------------------------------------------------------------------ section table
def _names(elements) -> str:
    return ", ".join(display_name(e) for e in elements)


def _spec_value(b: Builder, spec) -> str:
    value = getattr(spec, "_value", None)
    return value.tostring() if value is not None and hasattr(value, "tostring") else ""


def _enum_label(b: Builder, enum_class: str, value) -> str:
    return vfw.enum_name(enum_class, value) or str(value or "")


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    icon: str
    singular: str
    attr: str  # FrameSession attribute listing the elements
    add: Callable[[Builder], object]
    columns: tuple[tuple[str, str], ...]  # (field, header)
    row: Callable[[Builder, object], dict]
    form: Callable[[Builder, object], None]


SECTIONS: dict[str, Section] = {s.key: s for s in (
    Section(
        "experiments", "Experiments", "science", "experiment", "experiments",
        lambda b: b.session.add_experiment(),
        (("label", "Label"), ("conditions", "Conditions"), ("measurements", "Measurements")),
        lambda b, e: {"label": e.label, "conditions": _names(e.conditions), "measurements": _names(e.measurements)},
        experiment_form),
    Section(
        "specifications", "Specifications", "rule", "specification", "specifications",
        lambda b: b.session.add_specification(),
        (("feature", "Feature"), ("type", "Type"), ("value", "Value"),
         ("satisfied_by", "Satisfied by"), ("observed_by", "Observed by")),
        lambda b, s: {"feature": s.feature, "type": _enum_label(b, "PropertyType", s.type), "value": _spec_value(b, s),
                      "satisfied_by": _names(b.session.satisfied_by(s)),
                      "observed_by": _names(b.session.observed_by(s))},
        specification_form),
    Section(
        "properties", "Properties", "tune", "property", "properties",
        lambda b: b.session.add_property(),
        (("kind", "Kind"), ("datatype", "Datatype"), ("unit", "Unit"), ("range", "Range"), ("satisfies", "Satisfies")),
        lambda b, p: {"kind": KIND_LABELS[b.session.is_influence_factor(p)],
                      "datatype": _enum_label(b, "DataType", p.datatype), "unit": _enum_label(b, "UnitType", p.unit),
                      "range": f"{p.min} .. {p.max}",
                      "satisfies": _names([s for s in b.session.specifications if s.GUID in (p.satisfies or [])])},
        property_form),
    Section(
        "structures", "Model structure", "account_tree", "model structure", "model_structures",
        lambda b: b.session.add_model_structure(),
        (("model_type", "Model type"), ("model_ref", "Model reference"), ("inports", "Inports"),
         ("outports", "Outports")),
        lambda b, m: {"model_type": m.modelType or "", "model_ref": m.modelRef or "", "inports": _names(m.inports),
                      "outports": _names(m.outports)},
        structure_form),
    Section(
        "monitors", "Monitors", "monitor_heart", "monitor", "monitors",
        lambda b: b.session.add_monitor(),
        (("monitor_time", "Time"), ("observes", "Observes"), ("custom_code_file", "Code file")),
        lambda b, m: {"monitor_time": _enum_label(b, "MonitorTime", m.type), "observes": _names(m.observes or []),
                      "custom_code_file": custom_code_file(m) or ""},
        monitor_form),
)}
