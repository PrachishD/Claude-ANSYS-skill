"""Ansys Mechanical tools: run Mechanical's Python scripting API (ExtAPI, Model, DataModel...).

A session is either launched standalone (batch, no GUI) or attached to a Mechanical
system inside a Workbench project via workbench_open_mechanical.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from .common import default_workdir, find_executable, lock, quiet_stdout, tool, truncate

_mech = None
_source = None  # "standalone" or "workbench:<system>"


def running() -> bool:
    if _mech is None:
        return False
    try:
        return bool(_mech.is_alive)
    except Exception:
        return False


def status() -> dict:
    info = {"executable": find_executable("mechanical"), "running": running()}
    if running():
        info["session"] = _source
        with contextlib.suppress(Exception):
            info["project_directory"] = _mech.project_directory
    return info


def attach(session, source: str) -> None:
    """Bind an already-connected PyMechanical session (used by the Workbench tools)."""
    global _mech, _source
    with lock:
        _detach()
        _mech, _source = session, source


def _detach() -> None:
    global _mech, _source
    # A Workbench-hosted Mechanical belongs to the project (workbench_stop closes it);
    # only exit sessions we launched ourselves.
    if _mech is not None and _source == "standalone":
        with quiet_stdout(), contextlib.suppress(Exception):
            _mech.exit(force=True)
    _mech, _source = None, None


def _require():
    if not running():
        raise RuntimeError("Mechanical is not running. Call mechanical_start or workbench_open_mechanical first.")
    return _mech


def _run(script: str):
    """Run a script; turn gRPC failures into the script's own error message (minus .NET stack frames)."""
    try:
        return _require().run_python_script(script)
    except Exception as exc:
        details = exc.details() if callable(getattr(exc, "details", None)) else str(exc)
        lines = [ln for ln in str(details).splitlines() if not ln.lstrip().startswith("at ")]
        raise RuntimeError("Mechanical script error: " + "\n".join(lines).strip()) from None


@tool
def mechanical_start(restart: bool = False) -> dict:
    """Launch a standalone Ansys Mechanical session in batch mode (about 30-90 s).

    For analyses that should live in a Workbench project (linked systems, geometry
    from SpaceClaim/DesignModeler, parameters), use workbench_open_mechanical instead.
    """
    global _mech, _source
    with lock:
        if restart:
            _detach()
        if not running():
            exe = find_executable("mechanical")
            if not exe:
                raise RuntimeError("No Mechanical install found. Set ANSYS_MECHANICAL_EXEC to AnsysWBU.exe.")
            from ansys.mechanical.core import launch_mechanical

            with quiet_stdout():
                _mech = launch_mechanical(
                    exec_file=exe, batch=True, start_timeout=300, cleanup_on_exit=True, allow_input=False
                )
            _source = "standalone"
        return status()


def _export(target: Path, width: int, height: int, activate: str | None = None) -> Path:
    """Export the current graphics view (after activating `activate`, a script variable) to PNG."""
    target.parent.mkdir(parents=True, exist_ok=True)
    script = f"""
{f'{activate}.Activate()' if activate else ''}
Graphics.Camera.SetSpecificViewOrientation(ViewOrientationType.Iso)
Graphics.Camera.SetFit()
_s = Ansys.Mechanical.Graphics.GraphicsImageExportSettings()
_s.Resolution = GraphicsResolutionType.EnhancedResolution
_s.Background = GraphicsBackgroundType.White
_s.Width = {int(width)}
_s.Height = {int(height)}
_s.CurrentGraphicsDisplay = False
Graphics.ExportImage(r"{target}", GraphicsImageExportFormat.PNG, _s)
"ok"
"""
    _run(script)
    if not target.exists():
        raise RuntimeError(f"Mechanical did not write {target}")
    return target


def _image_dir() -> Path:
    with contextlib.suppress(Exception):
        return Path(_mech.project_directory)
    return default_workdir("mechanical")


@tool
def mechanical_run(script: str, images: list[str] | None = None) -> list:
    """Run a Mechanical Python script inside the session, optionally returning result images - ONE call.

    The script runs in Mechanical's scripting console with ExtAPI, Model, DataModel,
    Quantity, Ansys.* available; state persists between calls. The value of the LAST
    expression is returned -- end with `json.dumps({...})` for structured data.
    Put setup, solve and result extraction in one script: every call costs a round trip.

    Args:
        script: the Mechanical Python script.
        images: names of result objects defined in the script (e.g. ["vm", "uy"]); each is
            activated, exported to PNG (800x600) and returned with the text result.
    """
    from mcp.server.mcpserver import Image

    with lock, quiet_stdout():
        out = _run(script)
        paths = [_export(_image_dir() / f"{name}.png", 800, 600, activate=name) for name in (images or [])]
    text = truncate(str(out)) if out not in (None, "") else "(no value returned; end the script with an expression)"
    return [text] + [Image(path=str(p)) for p in paths]


@tool
def mechanical_export_image(path: str, width: int = 800, height: int = 600) -> list:
    """Export the current Mechanical graphics view to PNG. Prefer `images=[...]` in mechanical_run."""
    from mcp.server.mcpserver import Image

    target = Path(path) if Path(path).is_absolute() else _image_dir() / path
    with lock, quiet_stdout():
        _export(target, width, height)
    return [str(target), Image(path=str(target))]


@tool
def mechanical_stop() -> str:
    """Close the standalone Mechanical session, or detach from a Workbench-hosted one."""
    with lock:
        _detach()
    return "Mechanical session closed."
