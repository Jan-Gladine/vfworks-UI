"""The application shell: header, navigation, start page, element tables and shared dialogs."""
from __future__ import annotations

from pathlib import Path

from nicegui import run, ui

from vfbuilder import vfw
from vfbuilder.frame import FrameError, FrameSession
from vfbuilder.ui import overview
from vfbuilder.ui.filebrowser import browse
from vfbuilder.ui.forms import SECTIONS, Section, display_name
from vfbuilder.ui.state import AppState

SEVERITY_ICON = {"error": ("error", "negative"), "warning": ("warning", "orange-8")}

STATUS_SLOT = """
<q-td :props="props">
  <q-icon v-if="props.value == 'error'" name="error" color="negative" size="sm" />
  <q-icon v-else-if="props.value == 'warning'" name="warning" color="orange-8" size="sm" />
  <q-icon v-else name="check_circle" color="positive" size="sm" />
</q-td>
"""


class Builder:
    """One browser tab's view of the shared application state."""

    def __init__(self, state: AppState) -> None:
        self.state = state
        self.section = "frame"
        self.selected: dict[str, str | None] = {}
        self.busy = False

    @property
    def session(self) -> FrameSession:
        return self.state.session

    # ------------------------------------------------------------------ layout
    def build(self) -> None:
        ui.query("body").classes("bg-gray-100")
        with ui.header().classes("items-center gap-2 py-2"):
            ui.icon("verified", size="md")
            ui.label("vfbuilder").classes("text-lg font-bold")
            self.status()
            ui.space()
            self.actions()
        with ui.left_drawer(value=True).props("bordered width=250").classes("p-0"):
            self.nav()
        with ui.column().classes("w-full p-2 gap-4") as self.page_root:
            self.content()
        if not vfw.LOADER.done:
            # re-render once the background import of vfworks has finished
            def check() -> None:
                if vfw.LOADER.done:
                    timer.cancel()
                    self.refresh_all()

            timer = ui.timer(0.5, check)

    @ui.refreshable_method
    def status(self) -> None:
        if self.session is None:
            ui.label("no validity frame open").classes("text-sm")
            return
        ui.label(f"{self.session.package_name}{' *' if self.state.dirty else ''}").classes("text-sm").tooltip(
            str(self.session.source))
        errors = sum(i.severity == "error" for i in self.state.issues)
        warnings = len(self.state.issues) - errors
        if errors:
            ui.chip(f"{errors} error{'s' * (errors != 1)}", icon="error", color="negative", text_color="white",
                    on_click=lambda: self.go("overview")).props("clickable dense")
        if warnings:
            ui.chip(f"{warnings} warning{'s' * (warnings != 1)}", icon="warning", color="orange-8", text_color="white",
                    on_click=lambda: self.go("overview")).props("clickable dense")
        if not self.state.issues:
            ui.chip("no issues", icon="check_circle", color="positive", text_color="white").props("dense")

    @ui.refreshable_method
    def actions(self) -> None:
        ready = vfw.LOADER.ready
        for label, icon, handler, needs_frame in (
                ("New", "note_add", self.new_frame, False), ("Open", "folder_open", self.open_frame, False),
                ("Save", "save", self.save_frame, True), ("Close", "close", self.close_frame, True)):
            button = ui.button(label, icon=icon, on_click=handler).props("flat color=white no-caps")
            if not ready or (needs_frame and self.session is None):
                button.disable()

    @ui.refreshable_method
    def nav(self) -> None:
        if self.session is None:
            return

        def entry(key: str, title: str, icon: str, elements: list | None) -> None:
            item = ui.item(on_click=lambda: self.go(key)).props("clickable")
            if key == self.section:
                item.classes("bg-blue-100 font-medium")
            with item:
                with ui.item_section().props("avatar"):
                    ui.icon(icon)
                ui.item_section(title if elements is None else f"{title} ({len(elements)})")
                if elements:
                    severities = {self.state.severity(e) for e in elements}
                    level = "error" if "error" in severities else "warning" if "warning" in severities else None
                    if level:
                        with ui.item_section().props("side"):
                            ui.icon(SEVERITY_ICON[level][0], color=SEVERITY_ICON[level][1])

        with ui.list().classes("w-full"):
            entry("frame", "Frame", "badge", None)
            for sec in SECTIONS.values():
                entry(sec.key, sec.title, sec.icon, getattr(self.session, sec.attr))
            ui.separator()
            entry("overview", "Overview / Save", "hub", None)

    @ui.refreshable_method
    def content(self) -> None:
        if self.session is None:
            self.start_page()
        elif self.section == "frame":
            self.frame_page()
        elif self.section == "overview":
            overview.page(self)
        else:
            self.list_page(SECTIONS[self.section])

    # -------------------------------------------------------------- navigation
    def go(self, section: str) -> None:
        self.section = section
        self.nav.refresh()
        self.content.refresh()

    def open_element(self, guid: str | None) -> None:
        location = self.state.locate(guid) if guid else None
        if location is None:
            return
        section, top_guid = location
        self.selected[section] = top_guid
        self.go(section)

    def changed(self, structural: bool = False) -> None:
        """Call after every edit. ``structural`` rebuilds the page (elements added, removed or rebuilt)."""
        self.state.touch()
        self.status.refresh()
        self.nav.refresh()
        if structural:
            self.content.refresh()
        elif self.section in SECTIONS:
            self.table_area.refresh()
            self.issue_area.refresh()

    def refresh_all(self) -> None:
        self.state.revalidate()
        self.status.refresh()
        self.actions.refresh()
        self.nav.refresh()
        self.content.refresh()

    # ------------------------------------------------------------------- pages
    def start_page(self) -> None:
        with ui.card().classes("w-full max-w-3xl"):
            ui.label("vfbuilder").classes("text-xl font-medium")
            ui.label("Create a new validity frame or open an existing package. vfbuilder works directly on "
                     "the vfworks ValidityFrame: New creates the package with vfworks, Open loads it with "
                     "vfworks, Save writes it with vfworks' export().").classes("text-sm")
            loader = vfw.LOADER
            with ui.row().classes("items-center gap-2"):
                if not loader.done:
                    ui.spinner(size="sm")
                    ui.label("Loading vfworks (torch, ultralytics, pycaret)... this takes 15 to 25 seconds.").classes(
                        "text-sm")
                elif loader.error:
                    ui.icon("error", color="negative")
                    ui.label(f"vfworks could not be loaded: {loader.error}").classes("text-sm text-negative")
                else:
                    ui.icon("check_circle", color="positive")
                    ui.label(f"vfworks {vfw.vfw().version} loaded in {loader.seconds:.0f} s.").classes("text-sm")
            with ui.row().classes("gap-2"):
                for label, icon, handler in (("New validity frame", "note_add", self.new_frame),
                                             ("Open package", "folder_open", self.open_frame)):
                    button = ui.button(label, icon=icon, on_click=handler).props("no-caps")
                    if not loader.ready:
                        button.disable()

    def frame_page(self) -> None:
        s = self.session
        with ui.card().classes("w-full max-w-3xl"):
            ui.label("Validity frame").classes("text-lg font-medium")
            ui.label(f"Package: {s.source}").classes("text-sm break-all")
            if s.archive:
                ui.label(f"Working copy (vfworks unzipped the archive here; Save re-zips it): {s.package_root}").classes(
                    "text-sm break-all text-gray-600")
            ui.label(f"vfworks {vfw.vfw().version}").classes("text-sm text-gray-600")
        with ui.card().classes("w-full max-w-3xl"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("info", color="primary")
                ui.label("Not kept by vfworks").classes("text-lg font-medium")
            ui.label("These are vfworks limitations, not vfbuilder settings. vfworks' package files do not "
                     "record:").classes("text-sm")
            for note in ("whether a property is an influence factor: after reopening a package every property is "
                         "a property of interest again;",
                         "the frame's own name and description (the package name stands in for it);",
                         "a model structure's description."):
                ui.label(f"- {note}").classes("text-sm pl-2")

    def list_page(self, sec: Section) -> None:
        elements = getattr(self.session, sec.attr)
        current = next((e for e in elements if e.GUID == self.selected.get(sec.key)), None)
        if current is None and elements:
            current = elements[0]
        self.selected[sec.key] = current.GUID if current else None

        def add() -> None:
            element = sec.add(self)
            self.selected[sec.key] = element.GUID
            self.changed(structural=True)

        with ui.element("div").classes("grid grid-cols-1 xl:grid-cols-2 gap-4 w-full items-start"):
            with ui.card().classes("w-full"):
                with ui.row().classes("w-full items-center"):
                    ui.label(sec.title).classes("text-lg font-medium")
                    ui.space()
                    ui.button(f"Add {sec.singular}", icon="add", on_click=add).props("no-caps")
                self.table_area(sec)
            with ui.card().classes("w-full"):
                if current is None:
                    ui.label(f"No {sec.singular} yet. Use 'Add {sec.singular}' to create one.").classes("text-gray-600")
                    return
                with ui.row().classes("w-full items-center"):
                    ui.label(f"Edit {sec.singular}").classes("text-lg font-medium")
                    ui.space()
                    ui.button("Delete", icon="delete", color="negative",
                              on_click=lambda: self.confirm_delete(current)).props("flat no-caps")
                self.issue_area(current)
                sec.form(self, current)

    @ui.refreshable_method
    def table_area(self, sec: Section) -> None:
        elements = getattr(self.session, sec.attr)
        columns = [{"name": "status", "label": "", "field": "status", "align": "left"},
                   {"name": "name", "label": "Name", "field": "name", "align": "left"},
                   *({"name": f, "label": h, "field": f, "align": "left"} for f, h in sec.columns)]
        rows = [{"id": e.GUID, "status": self.state.severity(e) or "ok", "name": display_name(e), **sec.row(self, e)}
                for e in elements]
        table = ui.table(columns=columns, rows=rows, row_key="id", selection="single").classes("w-full")
        table.props("flat dense wrap-cells hide-selected-banner")
        table.add_slot("body-cell-status", STATUS_SLOT)
        table.selected = [r for r in rows if r["id"] == self.selected.get(sec.key)]

        def select(guid: str) -> None:
            if guid != self.selected.get(sec.key):
                self.selected[sec.key] = guid
                self.content.refresh()

        table.on("rowClick", lambda e: select(e.args[1]["id"]))
        table.on_select(lambda e: select(e.selection[0]["id"]) if e.selection else self.table_area.refresh())

    @ui.refreshable_method
    def issue_area(self, element) -> None:
        for issue in self.state.issues_for(element):
            icon, color = SEVERITY_ICON[issue.severity]
            with ui.row().classes("w-full items-center no-wrap gap-2"):
                ui.icon(icon, color=color, size="sm")
                owner = self.session.find(issue.element_id)
                prefix = "" if owner is None or owner is element else f"{display_name(owner)}: "
                ui.label(prefix + issue.message).classes("text-sm")

    # ----------------------------------------------------------------- dialogs
    async def confirm_delete(self, element) -> None:
        kind = self.session.kind(element)
        references = self.session.references_to(element)
        with ui.dialog() as dialog, ui.card().classes("w-[32rem] max-w-full"):
            ui.label(f"Delete {kind} '{display_name(element)}'?").classes("text-lg font-medium")
            if references:
                ui.label("It is referenced by:")
                with ui.column().classes("gap-0 pl-4"):
                    for ref in references:
                        ui.label(f"- {ref}").classes("text-sm")
                ui.label("These links will be removed.")
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
                ui.button("Delete", color="negative", on_click=lambda: dialog.submit(True))
        if await dialog:
            self.session.delete(element)
            self.changed(structural=True)

    async def ask_text(self, title: str, label: str, value: str = "") -> str | None:
        with ui.dialog() as dialog, ui.card().classes("w-96"):
            ui.label(title).classes("text-lg font-medium")
            field = ui.input(label, value=value).classes("w-full")
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat")
                ui.button("OK", on_click=lambda: dialog.submit((field.value or "").strip() or None))
        return await dialog

    async def confirm(self, title: str, message: str, action: str) -> bool:
        with ui.dialog() as dialog, ui.card().classes("w-[28rem] max-w-full"):
            ui.label(title).classes("text-lg font-medium")
            ui.label(message)
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
                ui.button(action, on_click=lambda: dialog.submit(True))
        return bool(await dialog)

    # ----------------------------------------------------------------- frames
    def reset_view(self) -> None:
        self.section, self.selected = "frame", {}
        self.refresh_all()

    async def discard_ok(self) -> bool:
        return not self.state.dirty or await self.confirm(
            "Discard unsaved changes?", "The open validity frame has changes that were not saved.", "Discard")

    async def _run(self, action, success: str) -> bool:
        """Run a frame action off the event loop (it may wait for vfworks to load)."""
        if self.busy:
            return False
        self.busy = True
        try:
            await run.io_bound(action)
        except (FrameError, vfw.VfworksUnavailable, OSError) as exc:
            ui.notify(str(exc), type="negative", multi_line=True)
            return False
        finally:
            self.busy = False
        self.reset_view()
        ui.notify(success, type="positive", multi_line=True)
        return True

    async def new_frame(self) -> None:
        if not await self.discard_ok():
            return
        values = {"directory": str(self.session.source.parent) if self.session else str(Path.cwd()),
                  "package": "", "name": ""}
        with ui.dialog() as dialog, ui.card().classes("w-[36rem] max-w-full"):
            ui.label("New validity frame").classes("text-lg font-medium")
            ui.label("vfworks creates the package folder (and its folder structure and templates) right away.").classes(
                "text-sm")

            async def browse_directory() -> None:
                path = await browse("Directory that will contain the package", values["directory"], mode="folder")
                if path is not None:
                    directory.value = str(path)

            with ui.row().classes("w-full items-center no-wrap gap-1"):
                directory = ui.input("Directory", value=values["directory"],
                                     on_change=lambda e: values.__setitem__("directory", e.value or "")).classes("grow")
                ui.button("Browse...", icon="folder_open", on_click=browse_directory).props("flat dense no-caps")
            ui.input("Package name (folder)", on_change=lambda e: values.__setitem__("package", e.value or "")).classes(
                "w-full")
            ui.input("Frame name (optional; vfworks does not save it)",
                     on_change=lambda e: values.__setitem__("name", e.value or "")).classes("w-full")
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
                ui.button("Create", on_click=lambda: dialog.submit(True))
        if not await dialog:
            return
        target = Path(values["directory"]) / values["package"].strip()
        await self._run(lambda: self.state.new(values["directory"], values["package"], values["name"]),
                        f"Created {target}")

    async def open_frame(self) -> None:
        if not await self.discard_ok():
            return
        start = self.session.source.parent if self.session else Path.cwd()
        path = await browse("Open a package folder or a .vf archive", start, mode="any", extensions=(".vf",))
        if path is not None:
            await self._run(lambda: self.state.open(path), f"Opened {path}")

    async def save_frame(self) -> None:
        if self.session is None:
            return
        try:
            saved = self.session.save()
        except OSError as exc:
            ui.notify(str(exc), type="negative")
            return
        errors = sum(i.severity == "error" for i in self.state.issues)
        self.status.refresh()
        ui.notify(f"Saved {saved}" + (f" (with {errors} validation error{'s' * (errors != 1)})" if errors else ""),
                  type="warning" if errors else "positive")

    async def close_frame(self) -> None:
        if await self.discard_ok():
            self.state.close()
            self.reset_view()
