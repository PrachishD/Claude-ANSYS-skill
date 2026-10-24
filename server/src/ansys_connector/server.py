"""Entry point: registers every product's tools on one MCP server."""

from __future__ import annotations

from pathlib import Path

from mcp.server.mcpserver import Image

from . import fluent, mapdl, mechanical, workbench
from .common import default_workdir, find_install, is_student, mcp, start_watchdog, tool


@tool
def ansys_status() -> dict:
    """Show the detected Ansys install, license edition, and the state of each product session."""
    found = find_install()
    return {
        "install_root": str(found[0]) if found else None,
        "version": found[1] if found else None,
        "student_edition": is_student(),
        "default_working_directory": str(default_workdir()),
        "mapdl": mapdl.status(),
        "mechanical": mechanical.status(),
        "fluent": fluent.status(),
        "workbench": workbench.status(),
    }


@tool
def show_image(path: str) -> list:
    """Return an image file (PNG/JPG) so it can be viewed, e.g. a plot exported from Mechanical or Fluent."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(path)
    return [str(p), Image(path=str(p))]


def _shutdown() -> None:
    for stop in (mapdl.mapdl_stop, mechanical.mechanical_stop, fluent.fluent_stop, workbench.workbench_stop):
        try:
            stop()
        except Exception:
            pass


def main() -> None:
    start_watchdog()
    try:
        mcp.run()
    finally:
        _shutdown()


if __name__ == "__main__":
    main()
