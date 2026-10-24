"""Mechanical APDL tools: launch the solver, pass APDL through, return compact results and plots.

Token economy: every tool call costs a full round trip of the conversation, so one
`mapdl_run` can build, solve, read parameters and render several plots, and it returns
only errors, warnings and the requested values unless verbose output is asked for.
"""

from __future__ import annotations

import contextlib
import json
import re
import time
from pathlib import Path

from mcp.server.mcpserver import Image

from .common import default_workdir, find_executable, lock, quiet_stdout, tool, truncate

_mapdl = None

VIEWS = {"iso": "1,1,1,1", "front": "1,0,0,1", "top": "1,0,1,0", "right": "1,1,0,0"}
MAX_WARNINGS = 5


def running() -> bool:
    try:
        return _mapdl is not None and not _mapdl.exited
    except Exception:
        return False


def status() -> dict:
    info = {"executable": find_executable("mapdl"), "running": running()}
    if running():
        info["version"] = _mapdl.version
        info["working_directory"] = _mapdl.directory
    return info


def _ensure(working_directory: str | None = None, nproc: int = 2):
    """Return the running session, launching it on first use."""
    global _mapdl
    if not running():
        exe = find_executable("mapdl")
        if not exe:
            raise RuntimeError("No MAPDL install found. Set ANSYS_MAPDL_EXEC to the ANSYSxxx executable.")
        from ansys.mapdl.core import launch_mapdl

        wd = Path(working_directory) if working_directory else default_workdir("mapdl")
        wd.mkdir(parents=True, exist_ok=True)
        with quiet_stdout():
            _mapdl = launch_mapdl(
                exec_file=exe, run_location=str(wd), nproc=nproc, override=True, start_timeout=240, loglevel="ERROR"
            )
    elif working_directory and Path(working_directory).resolve() != Path(_mapdl.directory).resolve():
        Path(working_directory).mkdir(parents=True, exist_ok=True)
        with quiet_stdout():
            _mapdl.cwd(working_directory)
    return _mapdl


def _blocks(text: str, kind: str) -> list[str]:
    """Pull '*** WARNING ***' / '*** ERROR ***' messages out of MAPDL output, one string each."""
    found = []
    for m in re.finditer(rf"\*\*\* {kind} \*\*\*.*?\n(.*?)(?:\n\s*\n|\Z)", text, re.S):
        msg = " ".join(m.group(1).split())
        if msg and msg not in found:
            found.append(msg)
    return found


def _compact(value):
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, float):
        return float(f"{value:.6g}")
    if isinstance(value, list):
        return [_compact(v) for v in value]
    return value


def _parameters(m, names: list[str] | None) -> dict:
    params = dict(m.parameters)
    if names:
        upper = {k.upper(): v for k, v in params.items()}
        params = {n.upper(): upper.get(n.upper()) for n in names}
    return {k: _compact(v) for k, v in params.items()}


def _render(m, commands: str, view: str, size: int, name: str | None) -> Path:
    wd = Path(m.directory)
    before = set(wd.glob("*.png"))
    setup = ["/SHOW,PNG,,0", "PNGR,COMP,1,-1", f"/GFILE,{int(size)}", "/RGB,INDEX,100,100,100,0", "/RGB,INDEX,0,0,0,15"]
    if view != "keep":
        setup += [f"/VIEW,1,{VIEWS.get(view, view)}", "/AUTO,1"]
    m.input_strings("\n".join(setup + [commands, "/SHOW,CLOSE"]))
    time.sleep(0.2)
    new = sorted(set(wd.glob("*.png")) - before, key=lambda p: p.stat().st_mtime)
    if not new:
        raise RuntimeError(f"MAPDL produced no image for: {commands!r}. Check that the mesh/results exist.")
    img = new[-1]
    if name:
        target = wd / (name if name.lower().endswith(".png") else name + ".png")
        img.replace(target)
        img = target
    return img


@tool
def mapdl_start(working_directory: str | None = None, nproc: int = 2, restart: bool = False) -> dict:
    """Launch MAPDL explicitly (optional: mapdl_run starts it automatically). Use to pick cores or restart."""
    with lock:
        if restart:
            mapdl_stop()
        _ensure(working_directory, nproc)
        return status()


@tool
def mapdl_run(
    commands: str,
    get: list[str] | None = None,
    plots: list[str] | None = None,
    view: str = "iso",
    image_size: int = 600,
    working_directory: str | None = None,
    verbose: bool = False,
) -> list:
    """Run APDL, then return requested parameters and plot images - all in ONE call.

    Starts MAPDL automatically on first use (~15-30 s). State persists between calls.
    Returns compact JSON: status, solver warnings, and the APDL parameters named in `get`
    (store results with *GET first), followed by one image per entry in `plots`.
    APDL errors are returned as a tool error containing the MAPDL error messages.

    Args:
        commands: APDL (newline separated). Build + solve + post-process in one go where possible.
        get: parameter names to return, e.g. ["F1", "F2", "SVM", "UMAX"].
        plots: plot command strings, each rendered to its own PNG, e.g.
            ["/POST1\\nSET,1,1\\nPLDISP,2", "SET,1,2\\nPLDISP,2"] or ["PLNSOL,S,EQV"].
        view: iso | front | top | right | keep.
        image_size: image height in pixels (600 is enough to read; larger costs more tokens).
        working_directory: folder for this study's files (switches the session's folder).
        verbose: also return MAPDL's full text output (large; only for debugging).
    """
    with lock, quiet_stdout():
        m = _ensure(working_directory)
        try:
            out = str(m.input_strings(commands))
        except Exception as exc:
            text = str(exc)
            errors = _blocks(text, "ERROR")
            raise RuntimeError("APDL error: " + (" | ".join(errors) if errors else truncate(text))) from None
        result: dict = {"status": "ok"}
        warnings = _blocks(out, "WARNING")
        if warnings:
            result["warnings"] = warnings[:MAX_WARNINGS] + (
                [f"... {len(warnings) - MAX_WARNINGS} more"] if len(warnings) > MAX_WARNINGS else []
            )
        if get:
            result["parameters"] = _parameters(m, get)
        images = [_render(m, cmd, view, image_size, None) for cmd in (plots or [])]
        if images:
            result["images"] = [str(p) for p in images]
        if verbose:
            result["output"] = truncate(out)
    return [json.dumps(result)] + [Image(path=str(p)) for p in images]


@tool
def mapdl_get_parameters(names: list[str] | None = None) -> dict:
    """Return APDL parameters (e.g. values stored with *GET). All parameters if names is empty."""
    with lock, quiet_stdout():
        return _parameters(_ensure(), names)


@tool
def mapdl_plot(commands: str, view: str = "iso", image_size: int = 600, filename: str | None = None) -> list:
    """Render one MAPDL plot (e.g. "PLNSOL,S,EQV") to PNG. Prefer `plots=[...]` in mapdl_run to save a call."""
    with lock, quiet_stdout():
        img = _render(_ensure(), commands, view, image_size, filename)
    return [str(img), Image(path=str(img))]


@tool
def mapdl_stop() -> str:
    """Exit MAPDL and release the license."""
    global _mapdl
    with lock:
        if _mapdl is not None:
            with quiet_stdout(), contextlib.suppress(Exception):
                _mapdl.exit()
        _mapdl = None
    return "MAPDL stopped."
