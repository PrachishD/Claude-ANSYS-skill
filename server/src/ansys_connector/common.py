"""Shared plumbing: the MCP server instance, tool registration and Ansys install discovery."""

from __future__ import annotations

import contextlib
import functools
import glob
import io
import os
import re
import sys
import threading
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

MAX_OUTPUT_CHARS = 30_000

mcp = MCPServer(
    "ansys",
    instructions=(
        "Unofficial connector to locally installed Ansys products. Each product has its own "
        "tools: mapdl_* (Mechanical APDL solver, driven with APDL), mechanical_* (Ansys "
        "Mechanical, driven with its Python scripting API), fluent_* (Fluent CFD via PyFluent) "
        "and workbench_* (the Workbench project, driven with IronPython journals). Start with "
        "ansys_status. Sessions keep their state between calls; stop them when finished to "
        "release licenses."
    ),
)

lock = threading.RLock()

# Product executables relative to an install's vXXX folder.
_EXECUTABLES = {
    "win32": {
        "mapdl": "ANSYS/bin/winx64/ANSYS{ver}.exe",
        "mechanical": "aisol/bin/winx64/AnsysWBU.exe",
        "fluent": "fluent/ntbin/win64/fluent.exe",
        "workbench": "Framework/bin/Win64/RunWB2.exe",
    },
    "linux": {
        "mapdl": "ansys/bin/ansys{ver}",
        "mechanical": "aisol/.workbench",
        "fluent": "fluent/bin/fluent",
        "workbench": "Framework/bin/Linux64/runwb2",
    },
}


@contextlib.contextmanager
def quiet_stdout():
    """MCP speaks JSON-RPC over stdout; keep library chatter off it."""
    with contextlib.redirect_stdout(sys.stderr):
        yield


@contextlib.contextmanager
def capture_stdout():
    """Collect anything printed (e.g. by user code run inside a session)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        yield buf


def truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    half = MAX_OUTPUT_CHARS // 2
    return f"{text[:half]}\n\n... [{len(text) - MAX_OUTPUT_CHARS} chars truncated] ...\n\n{text[-half:]}"


def tool(fn):
    """Register a tool whose failures reach Claude as readable text instead of a generic error."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError(f"{type(exc).__name__}: {exc}") from exc

    return mcp.tool()(wrapper)


def default_workdir(sub: str | None = None) -> Path:
    path = Path(os.environ.get("ANSYS_WORKDIR") or Path.home() / "ansys_runs")
    if sub:
        path = path / sub
    path.mkdir(parents=True, exist_ok=True)
    return path


def _install_roots() -> list[Path]:
    """Ansys version roots (the vXXX folders) from env vars and standard install paths."""
    roots = [Path(v) for k, v in os.environ.items() if re.fullmatch(r"AWP_ROOT\d{3}", k.upper())]
    if sys.platform == "win32":
        base = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ANSYS Inc"
        patterns = [base / "v*", base / "*" / "v*"]  # ANSYS Inc/v261, ANSYS Inc/ANSYS Student/v261
    else:
        patterns = [Path(p) for p in ("/usr/ansys_inc/v*", "/ansys_inc/v*", "/opt/ansys_inc/v*")]
    for pat in patterns:
        roots += [Path(p) for p in glob.glob(str(pat))]
    return [r for r in roots if re.fullmatch(r"v\d{3}", r.name.lower())]


def find_install() -> tuple[Path, str] | None:
    """Newest install as (vXXX root, "261"). ANSYS_ROOT overrides discovery."""
    if os.environ.get("ANSYS_ROOT"):
        root = Path(os.environ["ANSYS_ROOT"])
        return root, root.name.lower().lstrip("v")
    roots = _install_roots()
    if not roots:
        return None
    root = max(roots, key=lambda r: int(r.name[1:]))
    ver = root.name[1:]
    # PyAnsys libraries look for AWP_ROOTxxx; MCP clients don't always pass it through.
    os.environ.setdefault(f"AWP_ROOT{ver}", str(root))
    return root, ver


def find_executable(product: str) -> str | None:
    override = os.environ.get(f"ANSYS_{product.upper()}_EXEC")
    if override:
        return override
    found = find_install()
    if not found:
        return None
    root, ver = found
    rel = _EXECUTABLES["win32" if sys.platform == "win32" else "linux"][product].format(ver=ver)
    exe = root / rel
    return str(exe) if exe.exists() else None


_extra_pid_file: Path | None = None


def start_watchdog() -> None:
    """Launch the orphan guard (see watchdog.py) for this connector process."""
    global _extra_pid_file
    import subprocess
    import tempfile

    _extra_pid_file = Path(tempfile.gettempdir()) / f"ansys_connector_{os.getpid()}.pids"
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    subprocess.Popen(
        [sys.executable, "-m", "ansys_connector.watchdog", str(os.getpid()), str(_extra_pid_file)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        start_new_session=sys.platform != "win32",
    )


def register_pid(pid: int | None) -> None:
    """Have the watchdog also clean up a process that isn't our child (e.g. launched via WMI)."""
    if _extra_pid_file and pid and pid > 0:
        with open(_extra_pid_file, "a") as fh:
            fh.write(f"{pid}\n")


def is_student() -> bool:
    found = find_install()
    return bool(found and "student" in str(found[0]).lower())
