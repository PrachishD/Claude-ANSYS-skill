"""Ansys Workbench tools: drive the project schematic with Workbench (IronPython) journals.

Workbench is the hub: it creates any analysis system (Static Structural, Modal,
Fluid Flow (Fluent), ...), links systems, imports geometry and manages parameters.
The Mechanical or Fluent session behind a system can then be opened and driven with
the mechanical_* / fluent_* tools.
"""

from __future__ import annotations

import contextlib
import logging
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from . import fluent, mechanical
from .common import default_workdir, find_executable, lock, quiet_stdout, tool

_wb = None
_proc: subprocess.Popen | None = None
_workdir: Path | None = None

PORT_VAR = "ANSYS_FRAMEWORK_SERVER_PORT"
START_TIMEOUT_S = 480


def _user_env(name: str) -> str | None:
    """Read a persisted user environment variable (Workbench publishes its port there on Windows)."""
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return str(winreg.QueryValueEx(key, name)[0])
    except OSError:
        return None


def _launch(show_gui: bool, workdir: Path) -> tuple[subprocess.Popen, int]:
    """Start RunWB2 as OUR child process and return (process, gRPC port).

    PyWorkbench launches through WMI on Windows, which puts Workbench outside the MCP
    client's kill-on-close job, so it outlives a crashed connector and keeps its license.
    As a child process it is cleaned up with the connector.
    """
    exe = find_executable("workbench")
    if not exe:
        raise RuntimeError("No Workbench install found. Set ANSYS_ROOT to the vXXX folder.")
    prefix = uuid.uuid4().hex
    security = "wnua" if sys.platform == "win32" else "insecure"
    start = (
        f"StartServer(EnvironmentPrefix='{prefix}',"
        f"WorkingDirectory='{workdir.as_posix()}',Security='{security}')"
    )
    args = [exe] + (["-I"] if show_gui else ["--start-and-wait", "-nowindow"]) + ["-E", start]
    proc = subprocess.Popen(
        args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace"
    )

    found: dict[str, int] = {}

    def drain():  # read stdout (Linux reports the port here) and keep the pipe from filling
        for line in proc.stdout:
            if line.startswith(PORT_VAR + "=" + prefix):
                found["port"] = int(line.strip()[len(PORT_VAR) + 1 + len(prefix):])

    threading.Thread(target=drain, daemon=True).start()
    deadline = time.time() + START_TIMEOUT_S
    while time.time() < deadline:
        if "port" in found:
            return proc, found["port"]
        value = _user_env(PORT_VAR)
        if value and value.startswith(prefix):
            return proc, int(value[len(prefix):])
        if proc.poll() is not None:
            raise RuntimeError(f"Workbench exited during startup (code {proc.returncode}).")
        time.sleep(2)
    _kill_tree(proc)
    raise RuntimeError("Workbench did not report its server port within 8 minutes.")


def _kill_tree(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    import psutil

    try:
        procs = [psutil.Process(proc.pid)]
        procs += procs[0].children(recursive=True)
    except psutil.Error:
        return
    for p in procs:
        with contextlib.suppress(psutil.Error):
            p.terminate()
    _, alive = psutil.wait_procs(procs, timeout=15)
    for p in alive:
        with contextlib.suppress(psutil.Error):
            p.kill()


def running() -> bool:
    return _wb is not None


def status() -> dict:
    info = {"running": running()}
    if running():
        info["client_working_directory"] = str(_workdir)
    return info


class _Collect(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())


@contextlib.contextmanager
def _collect_logs():
    handler = _Collect()
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        yield handler.messages
    finally:
        root.removeHandler(handler)


def _require():
    if not running():
        raise RuntimeError("Workbench is not running. Call workbench_start first.")
    return _wb


@tool
def workbench_start(working_directory: str | None = None, show_gui: bool = False, restart: bool = False) -> dict:
    """Launch Ansys Workbench (about 60 s). show_gui=True opens the Workbench window so you can watch."""
    global _wb, _proc, _workdir
    with lock:
        if restart:
            workbench_stop()
        if not running():
            from ansys.workbench.core import connect_workbench

            wd = Path(working_directory) if working_directory else default_workdir("workbench")
            wd.mkdir(parents=True, exist_ok=True)
            proc, port = _launch(show_gui, wd)
            try:
                with quiet_stdout():
                    _wb = connect_workbench(
                        port=port, client_workdir=str(wd), security="wnua" if sys.platform == "win32" else "insecure"
                    )
            except Exception:
                _kill_tree(proc)
                raise
            _proc, _workdir = proc, wd
        return status()


@tool
def workbench_run(script: str) -> object:
    """Run a Workbench journal (IronPython) script in the project.

    Workbench scripting API is available (GetTemplate, GetSystem, Open, Save, Update,
    Parameters, ...). To return data, assign a JSON string to `wb_script_result`, e.g.
    `import json` ... `wb_script_result = json.dumps({"systems": [s.Name for s in GetAllSystems()]})`.
    Script errors are returned as tool errors.
    """
    with lock, quiet_stdout(), _collect_logs() as logs:
        result = _require().run_script_string(script, log_level="warning")
    errors = [m for m in logs if "error" in m.lower()]
    if errors:
        raise RuntimeError("\n".join(errors))
    if result is None:
        return {"result": None, "log": logs} if logs else "(script ran; it set no wb_script_result)"
    return result


@tool
def workbench_open_mechanical(system_name: str) -> dict:
    """Start Mechanical for a system in the project (e.g. "SYS") and bind it to the mechanical_* tools."""
    from ansys.mechanical.core import connect_to_mechanical

    with lock, quiet_stdout(), _collect_logs() as logs:
        port = _require().start_mechanical_server(system_name=system_name)
        if not port:
            raise RuntimeError("Workbench did not start Mechanical: " + "; ".join(logs))
        session = connect_to_mechanical(port=int(port), connect_timeout=300, cleanup_on_exit=False)
    mechanical.attach(session, f"workbench:{system_name}")
    return mechanical.status()


@tool
def workbench_open_fluent(system_name: str) -> dict:
    """Start Fluent for a Fluid Flow (Fluent) system in the project and bind it to the fluent_* tools."""
    import ansys.fluent.core as pyfluent

    with lock, quiet_stdout(), _collect_logs() as logs:
        info_file = _require().start_fluent_server(system_name=system_name)
        if not info_file:
            raise RuntimeError("Workbench did not start Fluent: " + "; ".join(logs))
        session = pyfluent.connect_to_fluent(server_info_file_name=info_file)
    fluent.attach(session, "solver", _workdir or default_workdir("fluent"))
    return fluent.status()


@tool
def workbench_stop() -> str:
    """Exit Workbench (unsaved project changes are lost; Save from a script first)."""
    global _wb, _proc
    with lock:
        if _wb is not None:
            with quiet_stdout(), contextlib.suppress(Exception):
                _wb.run_script_string("Reset()")
                _wb.run_script_string("internal_wbexit()")  # graceful exit, Workbench 2025 R2+
            with quiet_stdout(), contextlib.suppress(Exception):
                _wb.exit()  # client side: closes the gRPC connection
        if _proc is not None:
            with contextlib.suppress(subprocess.TimeoutExpired):
                _proc.wait(timeout=30)
            _kill_tree(_proc)
        # Mechanical/Fluent sessions hosted by this project are gone with it.
        if (mechanical.status().get("session") or "").startswith("workbench:"):
            mechanical.attach(None, None)
        _wb, _proc = None, None
    return "Workbench stopped."
