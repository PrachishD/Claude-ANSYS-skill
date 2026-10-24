"""Workbench must not outlive the connector, even when the MCP client exits abruptly."""
import asyncio, os, sys, time
import psutil
sys.path.insert(0, os.path.dirname(__file__))
from harness import call, connector

def wb_pids():
    return {p.pid for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() in ("runwb2.exe", "ansysfw.exe")}

async def main():
    before = wb_pids()
    async with connector() as s:
        await call(s, "workbench_start")
        started = wb_pids() - before
        print("workbench processes started:", sorted(started), flush=True)
        # leave without workbench_stop: the client tears the connector down
    deadline = time.time() + 60
    while time.time() < deadline and (wb_pids() & started):
        time.sleep(2)
    left = wb_pids() & started
    print("left running after client exit:", sorted(left))
    print("CLEANUP", "PASS" if started and not left else "FAIL")

asyncio.run(main())
