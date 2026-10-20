"""The ``vfbuilder`` command: starts the local server and opens the browser."""
from __future__ import annotations

import argparse
import sys

from nicegui import app, ui

from vfbuilder import vfw
from vfbuilder.frame import FrameError
from vfbuilder.ui.builder import Builder
from vfbuilder.ui.state import AppState


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="vfbuilder", description="GUI for authoring vfWorks validity frames.")
    parser.add_argument("package", nargs="?", help="package directory or .vf archive to open")
    parser.add_argument("--port", type=int, default=8642, help="port of the local server (default: 8642)")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    args = parser.parse_args(argv)

    state = AppState()  # starts importing vfworks in the background
    if args.package:
        print("loading vfworks...")
        try:
            state.open(args.package)
        except (FrameError, vfw.VfworksUnavailable) as exc:
            sys.exit(f"vfbuilder: {exc}")

    @ui.page("/")
    def index() -> None:
        Builder(state).build()

    app.on_startup(lambda: print(f"vfbuilder is running at http://localhost:{args.port} (Ctrl+C to stop)"))
    app.on_shutdown(state.close)  # releases vfworks' log file (and an archive's working copy)
    ui.run(host="127.0.0.1", port=args.port, title="vfbuilder", favicon="✅", reload=False,
           show=not args.no_browser, show_welcome_message=False)


if __name__ == "__main__":
    main()
