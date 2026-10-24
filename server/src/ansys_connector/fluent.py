"""Ansys Fluent tools: run PyFluent code against a live Fluent session.

Fluent's console transcript is streamed into a file (never to stdout, which carries
the MCP protocol) and the new part is returned after every call.
"""

from __future__ import annotations

import ast
import re
import contextlib
import time
import traceback
from pathlib import Path

from .common import capture_stdout, default_workdir, find_executable, lock, quiet_stdout, tool, truncate

_session = None
_mode = None
_namespace: dict = {}
_transcript: Path | None = None
_workdir: Path | None = None


def running() -> bool:
    try:
        return _session is not None and _session.is_active()
    except Exception:
        return False


def status() -> dict:
    info = {"executable": find_executable("fluent"), "running": running()}
    if running():
        info["mode"] = _mode
        info["working_directory"] = str(_workdir) if _workdir else None
        with contextlib.suppress(Exception):
            info["version"] = _session.get_fluent_version()
    return info


def _bind(session, mode: str, workdir: Path) -> None:
    global _session, _mode, _transcript, _workdir, _namespace
    import ansys.fluent.core as pyfluent

    _session, _mode, _workdir = session, mode, workdir
    _transcript = workdir / "fluent_transcript.txt"
    with contextlib.suppress(Exception):
        session.transcript.stop()
    session.transcript.start(file_name=str(_transcript), write_to_stdout=False)
    _namespace = {"session": session, "pyfluent": pyfluent, "workdir": str(workdir)}
    _namespace["solver" if mode == "solver" else "meshing"] = session


def attach(session, mode: str, workdir: Path) -> None:
    """Bind a session connected elsewhere (used by the Workbench tools)."""
    with lock:
        _close()
        _bind(session, mode, workdir)


def _close() -> None:
    global _session
    if _session is not None:
        with quiet_stdout(), contextlib.suppress(Exception):
            _session.exit()
    _session = None


def _require():
    if not running():
        raise RuntimeError("Fluent is not running. Call fluent_start first.")
    return _session


@tool
def fluent_start(
    mode: str = "solver",
    dimension: int = 3,
    precision: str = "double",
    processors: int = 2,
    working_directory: str | None = None,
    restart: bool = False,
) -> dict:
    """Launch Fluent without a GUI (about 30-60 s).

    Args:
        mode: "solver" or "meshing" (Fluent meshing; switch later with session.switch_to_solver()).
        dimension: 2 or 3.
        precision: "double" or "single".
        processors: number of parallel processes.
        working_directory: where case/data files, transcript and images go. Defaults to ~/ansys_runs/fluent.
        restart: close the current session first.
    """
    with lock:
        if restart:
            _close()
        if not running():
            import ansys.fluent.core as pyfluent

            wd = Path(working_directory) if working_directory else default_workdir("fluent")
            wd.mkdir(parents=True, exist_ok=True)
            kwargs = dict(
                mode=mode,
                dimension=dimension,
                precision=precision,
                processor_count=processors,
                ui_mode="no_gui",
                cwd=str(wd),
                start_timeout=300,
                start_transcript=False,
                cleanup_on_exit=True,
            )
            exe = find_executable("fluent")
            if exe:
                kwargs["fluent_path"] = exe
            with quiet_stdout():
                session = pyfluent.launch_fluent(**kwargs)
            _bind(session, mode, wd)
        return status()


def _transcript_size() -> int:
    return _transcript.stat().st_size if _transcript and _transcript.exists() else 0


def _transcript_since(offset: int) -> str:
    if not _transcript or not _transcript.exists():
        return ""
    time.sleep(0.3)  # let the streaming thread flush
    with open(_transcript, encoding="utf-8", errors="replace") as fh:
        fh.seek(offset)
        return fh.read().strip()


_RESIDUAL_ROW = re.compile(r"^\s*\d+\s+(\d\.\d+e[-+]\d+\s+)+")
_KEEP = re.compile(r"(?i)converged|warning|error|diverg|reversed flow|limited|not found|invalid|nan")


def _compact_transcript(text: str) -> str:
    """Drop per-iteration residual rows and banners; keep verdicts, warnings, errors, final residuals."""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    rows = [ln for ln in lines if _RESIDUAL_ROW.match(ln)]
    header = next((ln for ln in lines if ln.lstrip().startswith("iter ")), None)
    kept = []
    for ln in lines:
        if _RESIDUAL_ROW.match(ln) or ln.lstrip().startswith("iter "):
            continue
        if _KEEP.search(ln) and ln not in kept:
            kept.append(ln)
    if rows:
        kept += ([header] if header else []) + [rows[-1]] + [f"({len(rows)} iterations run)"]
    return "\n".join(kept[-25:])


def _save(s, object_name: str, kind: str, view: str, target: Path) -> Path:
    graphics = s.settings.results.graphics
    getattr(graphics, kind)[object_name].display()
    with contextlib.suppress(Exception):
        graphics.views.restore_view(view_name=view)
        graphics.views.auto_scale()
    # Resolution settings are inactive without a GUI; setting them anyway prints
    # "Error: object is not active" into the transcript, which looks like a real failure.
    for name, value in (("use_window_resolution", False), ("x_resolution", 800), ("y_resolution", 600)):
        with contextlib.suppress(Exception):
            setting = getattr(graphics.picture, name)
            if setting.is_active():
                setting.set_state(value)
    graphics.picture.save_picture(file_name=str(target))
    if not target.exists():
        raise RuntimeError(f"Fluent did not write {target}")
    return target


@tool
def fluent_run(code: str, verbose: bool = False, images: list[str] | None = None, view: str = "isometric") -> list:
    """Execute PyFluent Python code against the live Fluent session.

    Names available: `session` (also `solver` or `meshing`), `pyfluent`, `workdir`.
    Variables persist between calls - but do as much as possible per call (setup + iterate +
    report in one script): every call costs a full conversation round trip.
    Use the settings API, e.g. `solver.settings.file.read_case(file_name=...)`,
    `solver.settings.setup.models.viscous.model = "k-omega"`,
    `solver.settings.solution.run_calculation.iterate(iter_count=200)`, or TUI via
    `solver.execute_tui("/report/...")`. Returns printed output, the value of the final
    expression (end with the numbers you need) and a compact transcript: convergence
    verdict, warnings/errors and the last residual row. verbose=True returns the full transcript.
    images: names of contour objects (solver.settings.results.graphics.contour[...]) defined
    in the code; each is saved as PNG and returned in the same call (view: isometric|front|top...).
    """
    from mcp.server.mcpserver import Image

    with lock:
        _require()
        start = _transcript_size()
        tree = ast.parse(code, mode="exec")
        last_expr = tree.body.pop() if tree.body and isinstance(tree.body[-1], ast.Expr) else None
        value, error = None, None
        with capture_stdout() as out:
            try:
                exec(compile(tree, "<fluent_run>", "exec"), _namespace)
                if last_expr is not None:
                    value = eval(compile(ast.Expression(last_expr.value), "<fluent_run>", "eval"), _namespace)
            except Exception:
                error = traceback.format_exc(limit=4)
        parts = []
        if out.getvalue().strip():
            parts.append("[stdout]\n" + out.getvalue().strip())
        if value is not None:
            parts.append("[value]\n" + repr(value))
        transcript = _transcript_since(start)
        if transcript and not verbose:
            transcript = _compact_transcript(transcript)
        if transcript:
            parts.append("[fluent transcript]\n" + transcript)
        if error:
            parts.append("[error]\n" + error)
            raise RuntimeError(truncate("\n\n".join(parts)))
        folder = _workdir or default_workdir("fluent")
        with quiet_stdout():
            paths = [_save(_session, name, "contour", view, folder / f"{name}.png") for name in (images or [])]
    text = truncate("\n\n".join(parts)) or "(done, no output)"
    return [text] + [Image(path=str(p)) for p in paths]


@tool
def fluent_save_image(object_name: str, path: str, kind: str = "contour", view: str = "isometric") -> list:
    """Save one graphics object (contour/vector/mesh/pathline/scene) as PNG. Prefer `images=[...]` in fluent_run.

    Relative paths go in the Fluent working directory. view: isometric|front|back|top|bottom|left|right.
    """
    from mcp.server.mcpserver import Image

    s = _require()
    target = Path(path) if Path(path).is_absolute() else (_workdir or default_workdir("fluent")) / path
    with lock, quiet_stdout():
        _save(s, object_name, kind, view, target)
    return [str(target), Image(path=str(target))]


@tool
def fluent_stop() -> str:
    """Exit Fluent and release the license."""
    with lock:
        _close()
    return "Fluent stopped."
