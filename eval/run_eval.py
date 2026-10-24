"""Ansys connector eval runner.

Claude (via the Claude API) solves each case in eval/cases.py end to end with the connector's MCP
tools and the plugin's skills, then calls submit_answer; answers are graded against the derived
references. Cases run one at a time (Ansys licences), each with a fresh connector + solver.

Usage (from server/, inside its venv):
  python ../eval/run_eval.py --approve-harness          # user: approve this exact runner once
  python ../eval/run_eval.py --self-test                # grader oracle/null check, no API calls
  python ../eval/run_eval.py --cases S1-cantilever,M1-cantilever-modes   # pilot
  python ../eval/run_eval.py --max-total-usd 60         # full run, resumable
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cases import CASES  # noqa: E402

SERVER = ROOT / "server"
SKILLS = ROOT / "skills"
FLOW = ROOT / ".claude" / "hillclimb" / "ansys-solver"
HARNESS_FILES = [Path(__file__).resolve(), Path(__file__).resolve().parent / "cases.py"]

# $ per million tokens (Current Models table): input, output, cache write (1.25x input), cache read
PRICES = {
    "claude-fable-5-1": (10.0, 50.0, 12.5, 0.25),
    "claude-opus-5-5": (4.0, 20.0, 5.0, 0.20),
    "claude-sonnet-5-5": (2.0, 10.0, 2.5, 0.20),
}
FLAGS = ["singularity", "not_converged", "assumption_needed", "outside_validity", "solver_limit"]


# ----------------------------------------------------------------------------- grading

def grade(case: dict, submission: dict | None) -> tuple[dict, dict]:
    """Return (grade, detail). A value passes if |answer| is within tol of |expected| (sign conventions vary)."""
    answers = {a["key"]: a["value"] for a in (submission or {}).get("answers", [])}
    flags = set((submission or {}).get("flags", []))
    detail, hits, total = {}, 0, 0
    for key, exp in case["expected"].items():
        total += 1
        got = answers.get(key)
        if got is None:
            detail[key] = "missing"
            continue
        err = abs(abs(got) - abs(exp)) / abs(exp)
        ok = err <= case["tol"][key]
        hits += ok
        detail[key] = f"{got:.6g} vs {exp:.6g} ({100 * err:.2f}% err, tol {100 * case['tol'][key]:.0f}%) {'OK' if ok else 'FAIL'}"
    for flag in case["flags_required"]:
        total += 1
        ok = flag in flags
        hits += ok
        detail[f"flag:{flag}"] = "raised" if ok else "not raised"
    accuracy = hits / total if total else 0.0
    return {"pass": 1.0 if total and hits == total else 0.0, "accuracy": round(accuracy, 4)}, detail


def self_test() -> int:
    bad = 0
    for c in CASES:
        oracle = {"answers": [{"key": k, "value": v, "unit": c["units"][k]} for k, v in c["expected"].items()],
                  "flags": list(c["flags_required"])}
        g_or, _ = grade(c, oracle)
        g_null, _ = grade(c, {"answers": [], "flags": []})
        off = {"answers": [{"key": k, "value": v * 1.5, "unit": c["units"][k]} for k, v in c["expected"].items()],
               "flags": []}
        g_off, _ = grade(c, off)
        ok = g_or["pass"] == 1.0 and g_null["pass"] == 0.0 and g_off["pass"] == 0.0
        bad += not ok
        print(f"{c['id']:26s} oracle={g_or['pass']:.0f} null={g_null['pass']:.0f} 50%-off={g_off['pass']:.0f} {'ok' if ok else 'GRADER BUG'}")
    print("SELF-TEST", "PASS" if not bad else f"FAIL ({bad})")
    return 1 if bad else 0


# ----------------------------------------------------------------------------- harness gate

def harness_sha() -> str:
    h = hashlib.sha256()
    for p in HARNESS_FILES:
        h.update(p.read_bytes())
    return h.hexdigest()


def load_state() -> dict:
    p = FLOW / "_state.json"
    return json.loads(p.read_text()) if p.exists() else {}


def write_state(state: dict) -> None:
    FLOW.mkdir(parents=True, exist_ok=True)
    (FLOW / "_state.json").write_text(json.dumps(state, indent=2))


# ----------------------------------------------------------------------------- prompt + tools

def skill_index() -> dict[str, dict]:
    out = {}
    for d in sorted(SKILLS.iterdir()):
        f = d / "SKILL.md"
        if f.is_file():
            text = f.read_text(encoding="utf-8")
            m = re.search(r"^description:\s*(.+)$", text, re.M)
            out[d.name] = {"description": m.group(1).strip() if m else "", "text": text}
    return out


def system_prompt(skills: dict[str, dict]) -> str:
    listing = "\n".join(f"- {name}: {s['description']}" for name, s in skills.items())
    return f"""You are a simulation engineer working with a locally installed Ansys suite through the Ansys connector tools.
Solve the engineering problem you are given end to end with those tools. No person is available during this task:
do not ask questions - make reasonable engineering assumptions, state them in your summary, and keep going.

Skills hold the verified workflows for this connector. Before modelling, call load_skill for "ansys-simulation" and
for the skill that matches the problem, then follow them (they include how to verify results and how to keep
tool calls few).

Available skills:
{listing}

When you have a result you trust, call submit_answer exactly once:
- answers: one entry per key the problem asks for, as a plain number in the units requested.
- flags: raise "singularity" if a requested quantity is not physically meaningful (e.g. mesh-dependent stress at a
  sharp re-entrant corner) - in that case you may omit the value. Raise "not_converged", "assumption_needed",
  "outside_validity" or "solver_limit" when they apply.
- checks: the verification checks you actually ran (equilibrium, hand calculation, mesh convergence, ...).
- summary: two or three sentences on the method, assumptions and confidence.
Stop the Ansys sessions you started before submitting."""


def submit_tool() -> dict:
    return {
        "name": "submit_answer",
        "description": "Submit the final answer for grading. Call exactly once, at the end.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["answers", "flags", "checks", "summary"],
            "properties": {
                "answers": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["key", "value", "unit"],
                    "properties": {"key": {"type": "string"}, "value": {"type": "number"}, "unit": {"type": "string"}}}},
                "flags": {"type": "array", "items": {"type": "string", "enum": FLAGS}},
                "checks": {"type": "array", "items": {"type": "string"}},
                "summary": {"type": "string"},
            },
        },
    }


def skill_tool(skills: dict[str, dict]) -> dict:
    return {
        "name": "load_skill",
        "description": "Load a skill's full instructions (a SKILL.md workflow for the Ansys connector).",
        "input_schema": {"type": "object", "properties": {"name": {"type": "string", "enum": list(skills)}},
                         "required": ["name"]},
    }


def mcp_to_api(result) -> tuple[list, bool]:
    blocks = []
    for c in result.content:
        if c.type == "text":
            blocks.append({"type": "text", "text": c.text or "(empty)"})
        elif c.type == "image":
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": c.mimeType, "data": c.data}})
    return blocks or [{"type": "text", "text": "(no output)"}], bool(result.is_error)


def cost_of(model: str, usage: dict) -> float:
    pin, pout, pcw, pcr = PRICES.get(model, PRICES["claude-fable-5-1"])
    return (usage.get("input_tokens", 0) * pin + usage.get("output_tokens", 0) * pout
            + usage.get("cache_creation_input_tokens", 0) * pcw + usage.get("cache_read_input_tokens", 0) * pcr) / 1e6


# ----------------------------------------------------------------------------- one case

async def run_case(client, case: dict, args, skills: dict, system: str, run_dir: Path) -> dict:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    workdir = run_dir / "work" / case["id"]
    workdir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, ANSYS_WORKDIR=str(workdir))
    params = StdioServerParameters(command=sys.executable, args=["-W", "ignore", "-m", "ansys_connector"],
                                   env=env, cwd=str(SERVER))
    keys = ", ".join(f'"{k}" ({u})' for k, u in case["units"].items()) or "(none - see the problem)"
    user = f"{case['prompt']}\n\nReport these keys in submit_answer: {keys}. Use {workdir} as the working directory."
    trace = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    usage_tot = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    models, skills_loaded, submission = set(), [], None
    tool_calls = turns = nudges = 0
    stop_reason, status, fallback = None, "ok", False
    t0 = time.time()

    async with stdio_client(params) as (r, w), ClientSession(r, w) as mcp:
        await mcp.initialize()
        mcp_tools = (await mcp.list_tools()).tools
        tools = [{"name": t.name, "description": t.description or "", "input_schema": t.inputSchema} for t in mcp_tools]
        tools += [skill_tool(skills), submit_tool()]
        messages = [{"role": "user", "content": user}]
        while turns < args.max_turns:
            turns += 1
            async with client.beta.messages.stream(
                model=args.model, max_tokens=64000, system=system, tools=tools, messages=messages,
                cache_control={"type": "ephemeral"}, output_config={"effort": args.effort},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            ) as stream:
                msg = await stream.get_final_message()
            models.add(msg.model)
            u = msg.usage
            for k in usage_tot:
                usage_tot[k] += getattr(u, k, 0) or 0
            fallback |= any(getattr(b, "type", "") == "fallback" for b in msg.content)
            stop_reason = msg.stop_reason
            messages.append({"role": "assistant", "content": msg.content})
            text = "\n".join(b.text for b in msg.content if b.type == "text")
            uses = [b for b in msg.content if b.type == "tool_use"]
            if text:
                trace.append({"role": "assistant", "content": text})
            if cost_of(args.model, usage_tot) > args.max_case_usd:
                status = "budget_exceeded"
                break
            if stop_reason == "refusal":
                status = "refusal"
                break
            if stop_reason == "max_tokens":
                status = "truncated"
                break
            if not uses:
                if nudges < 1:
                    nudges += 1
                    messages.append({"role": "user", "content": "Call submit_answer now with your final values."})
                    continue
                status = "no_submission"
                break
            results = []
            for b in uses:
                tool_calls += 1
                trace.append({"role": "tool_call", "name": b.name, "content": json.dumps(b.input, indent=2)[:20000]})
                if b.name == "submit_answer":
                    submission = b.input
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": "Recorded."})
                    continue
                if b.name == "load_skill":
                    name = b.input.get("name", "")
                    skills_loaded.append(name)
                    body = skills.get(name, {}).get("text", f"Unknown skill {name!r}")
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": body})
                    trace.append({"role": "tool_result", "content": f"[skill {name}: {len(body)} chars]"})
                    continue
                try:
                    res = await mcp.call_tool(b.name, b.input)
                    blocks, is_err = mcp_to_api(res)
                except Exception as exc:
                    blocks, is_err = [{"type": "text", "text": f"Tool call failed: {exc}"}], True
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": blocks, "is_error": is_err})
                trace.append({"role": "tool_result", "content": "\n".join(
                    x["text"] if x["type"] == "text" else "[image]" for x in blocks)[:20000]})
            messages.append({"role": "user", "content": results})
            if submission is not None:
                break
        else:
            status = "max_turns"

    g, detail = grade(case, submission)
    served = sorted(models)
    return {
        "prompt_id": case["id"], "rep": 0, "prompt": case["prompt"], "tags": case["tags"],
        "status": status, "stop_reason": stop_reason, "grade": g, "explanation": detail,
        "answers": (submission or {}).get("answers", []), "flags": (submission or {}).get("flags", []),
        "checks": (submission or {}).get("checks", []), "summary": (submission or {}).get("summary", ""),
        "model": served[0] if len(served) == 1 else ",".join(served), "fallback": fallback,
        "usage": usage_tot, "latency_s": round(time.time() - t0, 1), "tool_calls": tool_calls, "turns": turns,
        "skills_loaded": skills_loaded, "meta": {"cost_usd_est": round(cost_of(args.model, usage_tot), 4)},
    }, trace


# ----------------------------------------------------------------------------- one case, real Claude Code

CLAUDE_EXE = Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
ANSWER_SCHEMA = {k: v for k, v in submit_tool()["input_schema"].items()}
EVAL_INSTRUCTIONS = (
    "You are being evaluated on an engineering problem. No person is available: do not ask questions; make and "
    "state reasonable assumptions and keep going. Use the Ansys connector tools and the plugin's skills. Your final "
    "answer is captured as structured output: answers (each key requested, plain number in the requested unit), "
    "flags (raise 'singularity' if a requested quantity is not physically meaningful, e.g. mesh-dependent stress at "
    "a sharp re-entrant corner - you may then omit that value; also 'not_converged', 'assumption_needed', "
    "'outside_validity', 'solver_limit' when they apply), checks (verification you actually ran) and summary. "
    "Stop the Ansys sessions you started before finishing."
)


def _uv_dir() -> str:
    return str(Path(os.environ.get("APPDATA", "")) / "Python" / "Python314" / "Scripts")


async def run_case_cli(case: dict, args, run_dir: Path) -> tuple[dict, list]:
    """Run one case through headless Claude Code (`claude -p`) with the development plugin loaded."""
    workdir = run_dir / "work" / case["id"]
    workdir.mkdir(parents=True, exist_ok=True)
    keys = ", ".join(f'"{k}" ({u})' for k, u in case["units"].items()) or "(none - see the problem)"
    prompt = f"{case['prompt']}\n\nReport these keys: {keys}. Work in this folder: {workdir}"
    cmd = [str(CLAUDE_EXE), "-p", "--output-format", "stream-json", "--verbose",
           "--plugin-dir", str(ROOT), "--setting-sources", "local", "--no-session-persistence",
           "--allowedTools", "mcp__plugin_ansys-connector_ansys", "Skill", "Read", "Glob",
           "--disallowedTools", "Bash", "PowerShell", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Agent",
           "--append-system-prompt", EVAL_INSTRUCTIONS,
           "--json-schema", json.dumps(ANSWER_SCHEMA),
           "--max-budget-usd", str(args.max_case_usd)]
    if args.model:
        cmd += ["--model", args.model]
    env = dict(os.environ, ANSYS_WORKDIR=str(workdir))
    env["PATH"] = _uv_dir() + os.pathsep + env.get("PATH", "")
    if args.engine == "cli-subscription":
        env.pop("ANTHROPIC_API_KEY", None)  # use the logged-in Claude subscription, never API credits
    t0 = time.time()
    proc = await asyncio.create_subprocess_exec(*cmd, cwd=str(workdir), env=env, stdin=asyncio.subprocess.PIPE,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                limit=64 * 1024 * 1024)
    proc.stdin.write(prompt.encode("utf-8"))
    await proc.stdin.drain()
    proc.stdin.close()
    trace = [{"role": "user", "content": prompt}]
    final, tool_calls, skills_loaded, models = {}, 0, [], set()
    try:
        async for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("{"):
                continue
            ev = json.loads(line)
            kind = ev.get("type")
            if kind == "system" and ev.get("subtype") == "init":
                models.add(ev.get("model", ""))
                trace.insert(0, {"role": "system", "content": f"model {ev.get('model')}; tools: {len(ev.get('tools', []))}; "
                                 f"mcp: {ev.get('mcp_servers')}; skills: {ev.get('skills', '')}"})
            elif kind == "assistant":
                for b in ev["message"].get("content", []):
                    if b.get("type") == "text" and b.get("text", "").strip():
                        trace.append({"role": "assistant", "content": b["text"]})
                    elif b.get("type") == "tool_use":
                        tool_calls += 1
                        if b["name"] == "Skill":
                            skills_loaded.append(str(b["input"].get("skill", b["input"])))
                        trace.append({"role": "tool_call", "name": b["name"], "content": json.dumps(b["input"], indent=2)[:20000]})
            elif kind == "user":
                content = ev.get("message", {}).get("content", [])
                for b in content if isinstance(content, list) else []:
                    if b.get("type") == "tool_result":
                        c = b.get("content")
                        text = c if isinstance(c, str) else "\n".join(
                            x.get("text", "[image]") if isinstance(x, dict) else str(x) for x in (c or []))
                        trace.append({"role": "tool_result", "content": text[:20000]})
            elif kind == "result":
                final = ev
    finally:
        try:
            await asyncio.wait_for(proc.wait(), 30)
        except asyncio.TimeoutError:
            proc.kill()
    stderr = (await proc.stderr.read()).decode("utf-8", "replace")[-2000:]
    if not final:
        raise RuntimeError(f"claude -p produced no result event (exit {proc.returncode}): {stderr}")
    submission = final.get("structured_output")
    usage = final.get("usage", {}) or {}
    usage_tot = {k: usage.get(k, 0) or 0 for k in
                 ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")}
    status = "ok"
    if final.get("is_error") or final.get("subtype") not in ("success", None):
        status = final.get("subtype") or "error"
    if submission is None and status == "ok":
        status = "no_submission"
    g, detail = grade(case, submission)
    model_usage = final.get("modelUsage") or {}
    served = sorted(model_usage) or sorted(m for m in models if m)
    if submission and submission.get("summary"):
        trace.append({"role": "assistant", "content": "FINAL ANSWER: " + json.dumps(submission, indent=2)})
    return {
        "prompt_id": case["id"], "rep": 0, "prompt": case["prompt"], "tags": case["tags"],
        "status": status, "stop_reason": final.get("stop_reason"), "grade": g, "explanation": detail,
        "answers": (submission or {}).get("answers", []), "flags": (submission or {}).get("flags", []),
        "checks": (submission or {}).get("checks", []), "summary": (submission or {}).get("summary", ""),
        "model": ",".join(served), "fallback": False, "usage": usage_tot,
        "latency_s": round(time.time() - t0, 1), "tool_calls": tool_calls, "turns": final.get("num_turns", 0),
        "skills_loaded": skills_loaded,
        "meta": {"engine": args.engine, "cost_usd_est": round(float(final.get("total_cost_usd") or 0.0), 4),
                 "billed_to": "subscription" if args.engine == "cli-subscription" else "api"},
    }, trace


# ----------------------------------------------------------------------------- main

async def main_async(args) -> int:
    import anthropic

    state = load_state()
    if state.get("harness_sha") != harness_sha():
        print("Harness not approved (runner or cases changed). Review eval/run_eval.py and eval/cases.py, then run:\n"
              "  python ../eval/run_eval.py --approve-harness")
        return 2
    run_dir = FLOW / args.variant
    (run_dir / "traces").mkdir(parents=True, exist_ok=True)
    results_path, errors_path = run_dir / "results.jsonl", run_dir / "errors.jsonl"
    done, spent = set(), 0.0
    for p in (results_path, errors_path):
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                if row.get("meta", {}).get("billed_to", "api") == "api":
                    spent += row.get("meta", {}).get("cost_usd_est", 0.0)
                if p == results_path:
                    done.add(row["prompt_id"])
    selected = [c for c in CASES if (args.cases and c["id"] in args.cases.split(","))
                or (not args.cases and (args.tier == "all" or c["tier"] == args.tier))]
    todo = [c for c in selected if c["id"] not in done][: args.limit or None]
    billed = args.engine != "cli-subscription"
    print(f"{len(todo)} case(s) via {args.engine} (model {args.model or 'CLI default'}); "
          f"{'API spend so far $%.2f, cap $%.2f' % (spent, args.max_total_usd) if billed else 'billed to your Claude subscription'}",
          flush=True)
    if args.engine == "api":
        client = anthropic.AsyncAnthropic(max_retries=4)
        skills = skill_index()
        system = system_prompt(skills)
    for case in todo:
        if billed and spent + args.max_case_usd > args.max_total_usd:
            print(f"Stopping: next case could exceed the ${args.max_total_usd:.2f} cap (spent ${spent:.2f}).")
            break
        print(f"- {case['id']} ...", flush=True)
        try:
            if args.engine == "api":
                job = run_case(client, case, args, skills, system, run_dir)
            else:
                job = run_case_cli(case, args, run_dir)
            row, trace = await asyncio.wait_for(job, args.timeout_s)
        except Exception as exc:
            kind = "timeout" if isinstance(exc, asyncio.TimeoutError) else type(exc).__name__
            err = {"prompt_id": case["id"], "rep": 0, "failure_class": kind, "error": str(exc)[:2000],
                   "meta": {"cost_usd_est": 0.0}}
            with open(errors_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(err) + "\n")
            print(f"  ERROR ({kind}): {str(exc)[:300]}", flush=True)
            continue
        if billed:
            spent += row["meta"]["cost_usd_est"]
        (run_dir / "traces" / f"{case['id']}_rep0.json").write_text(json.dumps(trace, indent=1), encoding="utf-8")
        with open(results_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        u = row["usage"]
        print(f"  {'PASS' if row['grade']['pass'] else 'FAIL'} acc={row['grade']['accuracy']:.2f} status={row['status']} "
              f"calls={row['tool_calls']} turns={row['turns']} {row['latency_s']:.0f}s ${row['meta']['cost_usd_est']:.2f} "
              f"(in {u['input_tokens']}, out {u['output_tokens']}, cache r/w {u['cache_read_input_tokens']}/"
              f"{u['cache_creation_input_tokens']}) model={row['model']}{' FALLBACK' if row['fallback'] else ''}", flush=True)
        for k, v in row["explanation"].items():
            print(f"     {k}: {v}", flush=True)
    rows = [json.loads(x) for x in results_path.read_text(encoding="utf-8").splitlines()] if results_path.exists() else []
    if rows:
        n, p = len(rows), sum(r["grade"]["pass"] for r in rows)
        half = 1.96 * ((p / n) * (1 - p / n) / n) ** 0.5
        print(f"\n{args.variant}: {p:.0f}/{n} passed ({100 * p / n:.0f}% +/- {100 * half:.0f}%), "
              f"est. spend ${sum(r['meta']['cost_usd_est'] for r in rows):.2f}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="baseline")
    ap.add_argument("--engine", default="cli-subscription", choices=["cli-subscription", "cli-api", "api"],
                    help="cli-subscription: real Claude Code on your plan (no API spend); cli-api: Claude Code billed "
                         "to ANTHROPIC_API_KEY; api: this file's own loop on the API")
    ap.add_argument("--model", default="", help="model id; empty = Claude Code's default (api engine: claude-fable-5-1)")
    ap.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--cases", default="")
    ap.add_argument("--tier", default="advanced", choices=["advanced", "core", "all"],
                    help="advanced (default): the 16 problems that need judgement or multi-step setup")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-turns", type=int, default=60)
    ap.add_argument("--max-case-usd", type=float, default=8.0)
    ap.add_argument("--max-total-usd", type=float, default=20.0)
    ap.add_argument("--timeout-s", type=float, default=2400.0)
    ap.add_argument("--approve-harness", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.engine == "api" and not args.model:
        args.model = "claude-fable-5-1"
    if args.approve_harness:
        state = load_state()
        state.update({"harness_sha": harness_sha(),
                      "metrics": [{"id": "pass", "label": "Pass", "kind": "binary"},
                                  {"id": "accuracy", "label": "Value accuracy", "kind": "continuous"}],
                      "perf_fields": ["latency_s", "tool_calls", "turns", "usage"]})
        write_state(state)
        print("Harness approved:", state["harness_sha"][:16])
        return 0
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
