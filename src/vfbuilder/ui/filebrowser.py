"""A file and folder browser for the machine the app runs on.

The browser tab cannot hand local paths to the server, so paths are picked in a
dialog that lists the server's (i.e. this computer's) file system.
"""
from __future__ import annotations

import os
import string
from pathlib import Path
from typing import Literal

from nicegui import ui

Mode = Literal["file", "folder", "any", "save"]
# a folder like %TEMP% can hold thousands of entries; rendering them all stalls the app
MAX_ENTRIES = 300


def _drives() -> list[Path]:
    if os.name != "nt":
        return []
    return [Path(f"{letter}:/") for letter in string.ascii_uppercase if Path(f"{letter}:/").exists()]


def _start(path: str | Path | None) -> Path:
    candidate = Path(path) if path else Path.home()
    while not candidate.is_dir() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate.resolve() if candidate.is_dir() else Path.home()


async def browse(title: str, start: str | Path | None = None, *, mode: Mode = "file",
                 extensions: tuple[str, ...] | None = None, save_name: str = "") -> Path | None:
    """Show the browser and return the chosen path, or None when cancelled.

    ``file`` picks a file, ``folder`` a folder, ``any`` either, and ``save`` a folder
    plus a file name. ``extensions`` limits the files listed (lower case, with dot).
    """
    current = _start(start)
    picked: Path | None = None
    name_filter = ""

    with ui.dialog() as dialog, ui.card().classes("w-[40rem] max-w-full"):
        ui.label(title).classes("text-lg font-medium")

        def go(path: Path) -> None:
            nonlocal current, picked, name_filter
            current, picked, name_filter = path, None, ""
            location.value = str(path)
            filter_input.value = ""
            listing.refresh()

        def go_typed() -> None:
            typed = Path((location.value or "").strip().strip('"'))
            if typed.is_dir():
                go(typed.resolve())
            elif typed.is_file() and mode in ("file", "any"):
                go(typed.parent.resolve())
                pick(typed.resolve())
            else:
                ui.notify(f"No such folder: {typed}", type="warning")

        def pick(path: Path) -> None:
            nonlocal picked
            picked = path
            listing.refresh()

        def set_filter(e) -> None:
            nonlocal name_filter
            name_filter = (e.value or "").strip().lower()
            listing.refresh()

        location = ui.input("Folder", value=str(current)).classes("w-full").props("dense")
        location.on("keydown.enter", go_typed)
        filter_input = ui.input("Filter by name", on_change=set_filter).classes("w-full").props("dense clearable")

        @ui.refreshable
        def listing() -> None:
            try:
                with os.scandir(current) as scan:
                    entries = [(e.is_dir(), e.name) for e in scan]
            except OSError as exc:
                entries = []
                ui.label(f"Cannot read this folder: {exc}").classes("text-negative")
            entries = sorted(((d, n) for d, n in entries if not n.startswith(".") and n != "__pycache__"
                              and (d or (mode != "folder" and (extensions is None or Path(n).suffix.lower() in extensions)))
                              and name_filter in n.lower()), key=lambda e: (not e[0], e[1].lower()))
            hidden = max(0, len(entries) - MAX_ENTRIES)
            entries = [(d, current / n) for d, n in entries[:MAX_ENTRIES]]
            with ui.scroll_area().classes("h-80 border rounded"), ui.list().props("dense").classes("w-full"):
                if current.parent != current:
                    with ui.item(on_click=lambda: go(current.parent)):
                        with ui.item_section().props("avatar"):
                            ui.icon("arrow_upward")
                        ui.item_section("..")
                else:
                    for drive in _drives():
                        with ui.item(on_click=lambda d=drive: go(d)):
                            with ui.item_section().props("avatar"):
                                ui.icon("storage")
                            ui.item_section(str(drive))
                for is_dir, entry in entries:
                    if is_dir:
                        with ui.item(on_click=lambda e=entry: go(e)):
                            with ui.item_section().props("avatar"):
                                ui.icon("folder", color="amber-8")
                            ui.item_section(entry.name)
                    else:
                        selectable = mode in ("file", "any")
                        item = ui.item(on_click=(lambda e=entry: pick(e)) if selectable else None)
                        if entry == picked:
                            item.classes("bg-blue-100")
                        with item:
                            with ui.item_section().props("avatar"):
                                ui.icon("description", color="grey-7")
                            ui.item_section(entry.name)
            if hidden:
                ui.label(f"{hidden} more entries not shown; type in 'Filter by name' or the folder path.").classes(
                    "text-sm text-orange-800")
            if mode in ("file", "any"):
                ui.label(f"Selected: {picked.name}" if picked else "Click a file to select it").classes("text-sm")

        listing()

        name_input = ui.input("File name", value=save_name).classes("w-full") if mode == "save" else None

        def confirm_file() -> None:
            if picked is None:
                ui.notify("Select a file first", type="warning")
            else:
                dialog.submit(picked)

        def confirm_save() -> None:
            name = (name_input.value or "").strip()
            if not name or Path(name).name != name:
                ui.notify("Enter a file name", type="warning")
            else:
                dialog.submit(current / name)

        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat")
            if mode in ("folder", "any"):
                ui.button("Use this folder", on_click=lambda: dialog.submit(current)).props(
                    "outline" if mode == "any" else "")
            if mode in ("file", "any"):
                ui.button("Use selected file", on_click=confirm_file)
            if mode == "save":
                ui.button("Save here", on_click=confirm_save)

    result = await dialog
    if dialog.client.has_socket_connection:  # the tab may have been closed or reloaded meanwhile
        dialog.delete()
    return result
