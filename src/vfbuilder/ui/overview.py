"""Overview / Save page: the link graph, all validation issues, saving and the vfworks log."""
from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import ui

from vfbuilder import vfw
from vfbuilder.graph import element_id_of, mermaid_source
from vfbuilder.script import render_script
from vfbuilder.ui.forms import display_name

if TYPE_CHECKING:
    from vfbuilder.ui.builder import Builder

SCRIPT_NAME = "populatePackage.py"


def page(b: Builder) -> None:
    _graph_card(b)
    with ui.element("div").classes("grid grid-cols-1 xl:grid-cols-2 gap-4 w-full items-start"):
        _issues_card(b)
        _save_card(b)


def _graph_card(b: Builder) -> None:
    s = b.session
    with ui.card().classes("w-full"):
        with ui.row().classes("w-full items-center gap-4"):
            ui.label("Links").classes("text-lg font-medium")
            ui.label("ports -> properties -> specifications -> monitors. Click a node to edit it.").classes(
                "text-sm text-gray-600")
            ui.space()
            for text, style in (("error", "border-color:#c10015;background:#fde7e9"),
                                ("warning", "border-color:#e08a00;background:#fff4d6")):
                ui.label(text).classes("text-xs px-2 border-2 rounded").style(style)
        if not (s.properties or s.specifications or s.monitors or s.model_structures):
            ui.label("Nothing to show yet. Add specifications, properties and monitors first.").classes("text-gray-600")
            return
        with ui.scroll_area().classes("w-full h-[26rem]"):
            ui.mermaid(mermaid_source(s, b.state.severity), config={"securityLevel": "loose"},
                       on_node_click=lambda e: b.open_element(element_id_of(e.node_id))).classes("w-full")


def _issues_card(b: Builder) -> None:
    issues = sorted(b.state.issues, key=lambda i: i.severity != "error")
    with ui.card().classes("w-full"):
        ui.label(f"Validation ({len(issues)})").classes("text-lg font-medium")
        if not issues:
            with ui.row().classes("items-center gap-2"):
                ui.icon("check_circle", color="positive", size="sm")
                ui.label("No issues.")
        with ui.list().props("dense").classes("w-full"):
            for issue in issues:
                element = b.session.find(issue.element_id)
                with ui.item(on_click=lambda i=issue: b.open_element(i.element_id)).props("clickable"):
                    with ui.item_section().props("avatar"):
                        if issue.severity == "error":
                            ui.icon("error", color="negative")
                        else:
                            ui.icon("warning", color="orange-8")
                    with ui.item_section():
                        ui.item_label(issue.message)
                        ui.item_label(display_name(element) if element else "").props("caption")


def _save_card(b: Builder) -> None:
    s = b.session
    with ui.card().classes("w-full"):
        ui.label("Save").classes("text-lg font-medium")
        ui.label(f"Package: {s.source}").classes("text-sm break-all")
        ui.label("Save calls the frame's export(), which rewrites the package's Metadata, Operational, "
                 "Processes and Experiments JSON" + (" and re-zips the archive." if s.archive else ".")).classes(
            "text-sm text-gray-600")

        async def save_archive() -> None:
            try:
                archive = s.save_archive()
            except OSError as exc:
                ui.notify(str(exc), type="negative")
                return
            b.status.refresh()
            ui.notify(f"Saved and zipped to {archive}", type="positive")

        async def write_script() -> None:
            path = s.source.parent / SCRIPT_NAME
            if path.exists() and not await b.confirm(
                    f"Replace {SCRIPT_NAME}?", f"{path} already exists and will be overwritten.", "Replace"):
                return
            try:
                path.write_text(render_script(s), encoding="utf-8")
            except OSError as exc:
                ui.notify(str(exc), type="negative")
                return
            ui.notify(f"Wrote {path}", type="positive")

        with ui.row().classes("w-full items-center gap-2"):
            ui.button("Save", icon="save", on_click=b.save_frame).props("no-caps")
            if not s.archive:
                ui.button("Save as .vf archive", icon="archive", on_click=save_archive).props("flat no-caps").tooltip(
                    "VF.zip(): saves, then writes <package>.vf next to the package folder")
            ui.button(f"Write {SCRIPT_NAME}", icon="code", on_click=write_script).props("flat no-caps").tooltip(
                "An equivalent vfworks script, next to the package")

        ui.label("vfworks log").classes("text-sm font-medium text-gray-600 mt-2")
        log = ui.log(max_lines=500).classes("w-full h-48 text-xs")
        for line in vfw.LOG.lines:
            log.push(line)
