"""Orphan guard: terminate Ansys processes the connector started if the connector dies.

MCP clients can kill the connector without letting it shut its sessions down, and on
Windows child processes outlive their parent - leaving solvers running and holding
licenses. This watchdog runs as a separate process, periodically records the
connector's descendants (plus extra PIDs it registers, e.g. Workbench, which is started
through WMI rather than as a child), and kills them once the connector is gone.

Usage: python -m ansys_connector.watchdog <connector_pid> <extra_pid_file>
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import psutil

POLL_S = 2.0


def _tree(proc: psutil.Process) -> list[psutil.Process]:
    try:
        return [proc, *proc.children(recursive=True)]
    except psutil.Error:
        return []


def main(parent_pid: int, extra_file: Path) -> None:
    me = psutil.Process()
    try:
        parent = psutil.Process(parent_pid)
    except psutil.Error:
        return
    tracked: dict[int, float] = {}  # pid -> create_time (guards against PID reuse)

    while True:
        if not parent.is_running():
            break
        roots = _tree(parent)[1:]
        if extra_file.exists():
            for line in extra_file.read_text().split():
                try:
                    roots.append(psutil.Process(int(line)))
                except (ValueError, psutil.Error):
                    pass
        seen = {}
        for root in roots:
            for p in _tree(root):
                if p.pid != me.pid:
                    try:
                        seen[p.pid] = p.create_time()
                    except psutil.Error:
                        pass
        tracked = seen
        time.sleep(POLL_S)

    victims = []
    for pid, created in tracked.items():
        try:
            p = psutil.Process(pid)
            if abs(p.create_time() - created) < 1e-3:
                victims.append(p)
        except psutil.Error:
            pass
    for p in victims:
        try:
            p.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(victims, timeout=10)
    for p in alive:
        try:
            p.kill()
        except psutil.Error:
            pass
    try:
        extra_file.unlink()
    except OSError:
        pass


if __name__ == "__main__":
    main(int(sys.argv[1]), Path(sys.argv[2]))
