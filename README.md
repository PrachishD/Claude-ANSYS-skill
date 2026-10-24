# Ansys Connector for Claude

**Unofficial.** An MCP connector and Claude Code plugin that lets Claude drive the Ansys products
installed on your own machine:

| Product | Driven with | Tools |
|---|---|---|
| Mechanical APDL | APDL commands | `mapdl_run` (auto-starts; `get=`, `plots=`), `mapdl_start`, `mapdl_get_parameters`, `mapdl_plot`, `mapdl_stop` |
| Mechanical | Mechanical Python scripting (ExtAPI) | `mechanical_run` (`images=`), `mechanical_start`, `mechanical_export_image`, `mechanical_stop` |
| Fluent | PyFluent (settings API / TUI) | `fluent_run` (`images=`), `fluent_start`, `fluent_save_image`, `fluent_stop` |
| Workbench | Workbench journals (IronPython) | `workbench_start`, `workbench_run`, `workbench_open_mechanical`, `workbench_open_fluent`, `workbench_stop` |
| General | | `ansys_status`, `show_image` |

**Built to use few tokens.** Every tool call re-sends the whole conversation, so each study
runs in as few calls as possible:
- One `mapdl_run` builds, solves, returns the requested `*GET` values (`get=[...]`) and renders
  plots (`plots=[...]`), and it starts the solver itself.
- Tool replies contain only errors, warnings and the values asked for. Solver echo is dropped,
  and Fluent's residual tables are cut to the convergence verdict.
- Images default to 800×600, about 650 tokens each.

A modal study that used to take 22 round trips should now need about 4.

The connector is a thin pipe and has no FEA or CFD logic of its own. Claude writes the input, and
the engineering method lives in **skills** that Claude follows. Each skill was checked against
a closed-form solution:

| Skill | Covers | Verified against |
|---|---|---|
| `ansys-simulation` | product choice, session hygiene, the verification checklist | |
| `static-structural` | stress, deflection, safety factor | cantilever tip deflection (Euler–Bernoulli) |
| `modal-analysis` | natural frequencies, mode shapes | cantilever f1 |
| `buckling-analysis` | eigenvalue and nonlinear buckling | Euler column |
| `thermal-analysis` | steady and transient conduction, thermal stress | 1D conduction, restrained bar σ = EαΔT |
| `dynamic-response` | harmonic and transient structural | resonance peak, 2× dynamic amplification |
| `workbench-mechanical` | Workbench projects, CAD import, Mechanical scripting | cantilever static and modal in Workbench-hosted Mechanical |
| `fluent-cfd` | Fluent setup, solve, reports, convergence | mixing elbow mass and energy balance |

The benchmarks are in [`server/tests`](server/tests) and run against your own install.

**Worked example:** [motor mounting bracket](examples/motor-bracket) covers a static and modal study run through the connector, then verified independently. The checks passed, but a closer look at an input assumption, the motor's rotary inertia, turned "no resonance" into a resonance risk.

## Requirements

- **Ansys 2024 R2 or newer** (Mechanical APDL, Mechanical, Fluent, Workbench), including the free
  [Ansys Student](https://www.ansys.com/academic/students) edition. The connector finds installs
  through `AWP_ROOTxxx` or the standard install folders.
- **Python 3.12+** and **[uv](https://docs.astral.sh/uv/)** (`pip install uv`). The connector's
  dependencies (PyMAPDL, PyMechanical, PyFluent, PyWorkbench, MCP) install automatically on first start.
- Windows is tested. Linux should work for MAPDL, Mechanical and Fluent; Workbench automation is Windows-first.
- On Windows, keep the clone in a short path (for example `C:\dev\Claude-ANSYS-connector`), or
  [enable long paths](https://learn.microsoft.com/windows/win32/fileio/maximum-file-path-limitation).
  Some dependency files are nested deeply enough to break the 260-character limit.

## Install

### Claude Code (plugin: connector and skills)
```
/plugin marketplace add PrachishD/Claude-ANSYS-connector
/plugin install ansys-connector@ansys-connector
```
or, from a local clone:
```
claude plugin marketplace add ./Claude-ANSYS-connector
claude plugin install ansys-connector@ansys-connector
```

### Any MCP client (connector only)
```json
{
  "mcpServers": {
    "ansys": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/Claude-ANSYS-connector/server", "ansys-connector"]
    }
  }
}
```

## Configuration (optional environment variables)

| Variable | Purpose |
|---|---|
| `ANSYS_ROOT` | Ansys version folder (e.g. `C:\Program Files\ANSYS Inc\v261`) when auto-detection picks the wrong one |
| `ANSYS_MAPDL_EXEC`, `ANSYS_MECHANICAL_EXEC`, `ANSYS_FLUENT_EXEC` | explicit executables |
| `ANSYS_WORKDIR` | default folder for runs (default `~/ansys_runs`) |

## Good to know

- **Licensing:** the connector uses your Ansys license. Sessions hold licenses until stopped, so
  ask Claude to stop them when you're done. Every solver is started as a child of the
  connector, and a watchdog covers the rest, so if the MCP client exits or the connector
  crashes, no Ansys process keeps running and holding a license.
- **Ansys Student:**
  - Structural and thermal models are capped at 128k nodes; Fluent at 1M cells.
  - Standalone Mechanical can't solve under the Student license; the skills route Mechanical solves through Workbench, which works.
- **Security:** `fluent_run` executes Python in the connector process, and every tool runs
  solver input on your machine. Only connect the connector to clients and models you trust.
- Simulation results are only as good as the model. The skills make Claude verify against
  hand calculations, equilibrium and mesh convergence, but engineering judgement and sign-off stay with you.

## Tests

```
cd server
uv run python tests/test_mapdl_benchmarks.py   # 6 analysis types vs closed-form
uv run python tests/test_workbench.py          # Workbench + Mechanical static & modal
uv run python tests/test_fluent.py             # Fluent mixing elbow conservation
uv run python tests/test_cleanup.py            # Workbench is cleaned up when the client exits
```
The tests launch real solvers and use your license; the full suite takes about 30 minutes.

## Disclaimer

Not affiliated with, endorsed by or supported by Ansys, Inc. or Synopsys, Inc. "Ansys",
"Fluent", "Mechanical" and "Workbench" are trademarks of their respective owners. This project
only automates software you have installed and licensed yourself. MIT licensed.
