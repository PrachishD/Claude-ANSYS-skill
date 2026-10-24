"""Tiny MCP client used by the product tests: launches the connector over stdio like Claude does."""
import json, os, sys
from contextlib import asynccontextmanager
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

@asynccontextmanager
async def connector():
    params = StdioServerParameters(command=sys.executable, args=["-W", "ignore", "-m", "ansys_connector"], env=dict(os.environ))
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        yield s

async def call(s, tool, **args):
    res = await s.call_tool(tool, args)
    text = res.content[0].text if res.content else ""
    if res.is_error:
        raise RuntimeError(f"{tool} failed:\n{text}")
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text

def check(name, got, want, rel_tol):
    err = abs(got - want) / abs(want)
    ok = err <= rel_tol
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {got:.6g} vs {want:.6g} ({100*err:.2f}% error, tol {100*rel_tol:.0f}%)")
    return ok
