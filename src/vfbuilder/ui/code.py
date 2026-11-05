"""Code files page: edit monitor functions (Resources/monitors) and model loaders (Resources/loaders).

The editor only reads and writes the files. vfbuilder never runs them; vfworks imports a
monitor's file when the monitor is added (on open, or when vfbuilder rebuilds it) and a
loader when a model is loaded.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import ui

from vfbuilder import package_files as pf
from vfbuilder.ui.forms import display_name

if TYPE_CHECKING:
    from vfbuilder.ui.builder import Builder

FOLDER_TITLES = {pf.MONITORS: "Monitor functions", pf.LOADERS: "Model loaders"}
FOLDER_HINTS = {
    pf.MONITORS: "validate(monitor=None, **kwargs) returns {feature: bool}. vfworks imports the file when a "
                 "monitor using it is added to the frame.",
    pf.LOADERS: "load_model(model_location, validityframe=None) returns the model. The file name without .py is "
                "the model type; vfworks imports it when the model is loaded.",
}
EDITOR_CSS = """
.cm-vfb-error { background-color: #fde7e9; }
.cm-vfb-warning { background-color: #fff4d6; }
"""

Key = tuple[str, str]  # (folder, file name)


def page(b: Builder) -> None:
    root = b.session.package_root
    files = {folder: pf.list_code_files(root, folder) for folder in pf.FOLDERS}  # to choose the selection
    if b.code_selected and b.code_selected[1] not in files.get(b.code_selected[0], []):
        b.code_selected = None
    if b.code_selected is None:
        first = next(((f, n) for f in pf.FOLDERS for n in files[f] if n != pf.TEMPLATES[f]), None)
        b.code_selected = first or next(((f, n) for f in pf.FOLDERS for n in files[f]), None)

    with ui.element("div").classes("grid grid-cols-1 xl:grid-cols-[22rem_1fr] gap-4 w-full items-start"):
        with ui.card().classes("w-full"):
            ui.label("Code files").classes("text-lg font-medium")
            if b.session.archive:
                ui.label("These files are in the archive's working copy; Save writes them into the .vf.").classes(
                    "text-xs text-gray-600")

            @ui.refreshable
            def file_lists() -> None:
                for folder in pf.FOLDERS:
                    _file_list(b, folder, pf.list_code_files(b.session.package_root, folder))

            file_lists()
        with ui.card().classes("w-full"):
            if b.code_selected is None:
                ui.label("No code files in this package.").classes("text-gray-600")
            else:
                _editor(b, *b.code_selected, file_lists.refresh)


def _file_list(b: Builder, folder: str, names: list[str]) -> None:
    s = b.session
    with ui.row().classes("w-full items-center mt-2"):
        ui.label(FOLDER_TITLES[folder]).classes("text-sm font-medium text-gray-600")
        ui.space()

        async def new_file() -> None:
            name = await b.ask_text(f"New {FOLDER_TITLES[folder][:-1].lower()}", "File name",
                                    "my_monitor.py" if folder == pf.MONITORS else "my_model_loader.py")
            if not name:
                return
            try:
                created = pf.create_from_template(s.package_root, folder, name)
            except pf.PackageFileError as exc:
                ui.notify(str(exc), type="negative")
                return
            s.code_file_changed()
            b.code_selected = (folder, created.name)
            b.changed(structural=True)

        ui.button("New", icon="add", on_click=new_file).props("flat dense no-caps").tooltip(
            f"Copy of vfworks' template {pf.TEMPLATES[folder]}")
    with ui.list().props("dense").classes("w-full"):
        for name in names:
            key = (folder, name)
            users = s.code_users(folder, name)
            problems = pf.check_file(s.package_root, folder, name)
            item = ui.item(on_click=lambda k=key: _select(b, k)).props("clickable")
            if key == b.code_selected:
                item.classes("bg-blue-100")
            with item:
                with ui.item_section():
                    ui.item_label(name + ("  *" if key in b.code_buffers else ""))
                    if name == pf.TEMPLATES[folder]:
                        caption = "vfworks template"
                    elif users:
                        caption = "used by " + ", ".join(display_name(u) for u in users)
                    else:
                        caption = "not used"
                    ui.item_label(caption).props("caption")
                if problems:
                    level = "error" if any(p.severity == "error" for p in problems) else "warning"
                    with ui.item_section().props("side"):
                        ui.icon(level, color="negative" if level == "error" else "orange-8", size="sm")


def _select(b: Builder, key: Key) -> None:
    if key != b.code_selected:
        b.code_selected = key  # unsaved text of the previous file stays in b.code_buffers
        b.content.refresh()


def _editor(b: Builder, folder: str, name: str, refresh_list) -> None:
    s = b.session
    key = (folder, name)
    try:
        on_disk = pf.read_code(s.package_root, folder, name)
    except pf.PackageFileError as exc:
        ui.label(str(exc)).classes("text-negative")
        return
    text = b.code_buffers.get(key, on_disk)

    with ui.row().classes("w-full items-center gap-2"):
        ui.label(f"Resources/{folder}/{name}").classes("text-lg font-medium")

        @ui.refreshable
        def unsaved_badge() -> None:
            if key in b.code_buffers:
                ui.badge("unsaved changes", color="orange-8")

        unsaved_badge()
        ui.space()

        def save(_=None) -> None:
            current = editor.value
            try:
                pf.write_code(s.package_root, folder, name, current)
            except pf.PackageFileError as exc:
                ui.notify(str(exc), type="negative")
                return
            b.code_buffers.pop(key, None)
            s.code_file_changed()
            problems = pf.check_code(current, folder)
            errors = [p for p in problems if p.severity == "error"]
            note = f" ({len(errors)} error{'s' * (len(errors) != 1)})" if errors else ""
            ui.notify(f"Saved {name}{note}" + ("; Save the frame to update the archive" if s.archive else ""),
                      type="warning" if errors else "positive")
            # keep the editor (and its cursor); refresh what depends on the file
            b.state.touch()
            b.status.refresh()
            b.nav.refresh()
            unsaved_badge.refresh()
            refresh_list()

        def revert() -> None:
            b.code_buffers.pop(key, None)
            b.content.refresh()

        async def delete() -> None:
            users = s.code_users(folder, name)
            message = f"Resources/{folder}/{name} is deleted from the package."
            if users:
                message += " It is still used by " + ", ".join(display_name(u) for u in users) + "."
            if not await b.confirm(f"Delete {name}?", message, "Delete"):
                return
            try:
                pf.delete_code(s.package_root, folder, name)
            except pf.PackageFileError as exc:
                ui.notify(str(exc), type="negative")
                return
            b.code_buffers.pop(key, None)
            b.code_selected = None
            s.code_file_changed()
            b.changed(structural=True)

        ui.button("Save", icon="save", on_click=save).props("no-caps").tooltip("Ctrl+S").mark("code-save")
        ui.button("Revert", icon="undo", on_click=revert).props("flat no-caps").tooltip("Back to the file on disk")
        delete_button = ui.button("Delete", icon="delete", color="negative", on_click=delete).props("flat no-caps")
        if name == pf.TEMPLATES[folder]:
            delete_button.disable()

    users = s.code_users(folder, name)
    with ui.row().classes("w-full items-center gap-1"):
        ui.label("Used by:").classes("text-sm text-gray-600")
        for user in users:
            ui.chip(display_name(user), on_click=lambda u=user: b.open_element(u.GUID)).props("outline clickable dense")
        if not users:
            ui.label("nothing" if name != pf.TEMPLATES[folder] else "nothing (vfworks copies new files from it)").classes(
                "text-sm")
    ui.label(FOLDER_HINTS[folder]).classes("text-xs text-gray-600")

    @ui.refreshable
    def problems_area(current: str) -> None:
        for problem in pf.check_code(current, folder):
            with ui.row().classes("w-full items-center no-wrap gap-2"):
                ui.icon(problem.severity, color="negative" if problem.severity == "error" else "orange-8", size="sm")
                ui.label(str(problem)).classes("text-sm")

    def mark(current: str) -> None:
        problems = [p for p in pf.check_code(current, folder) if p.line]
        editor.decorations = [{"kind": "line", "line": p.line, "class": f"cm-vfb-{p.severity}"}
                              for p in problems if p.line <= current.count("\n") + 1]
        editor.line_tooltips = {p.line: p.message for p in problems}

    def on_change(e) -> None:
        was_unsaved = key in b.code_buffers
        if e.value == pf.read_code(s.package_root, folder, name):
            b.code_buffers.pop(key, None)
        else:
            b.code_buffers[key] = e.value
        if (key in b.code_buffers) != was_unsaved:
            unsaved_badge.refresh()
            refresh_list()
            b.nav.refresh()
        problems_area.refresh(e.value)
        mark(e.value)

    editor = ui.codemirror(text, language="Python", on_change=on_change, keymap={"Mod-s": save}).classes(
        "w-full h-[60vh] border rounded").mark("code-editor")
    mark(text)
    problems_area(text)
