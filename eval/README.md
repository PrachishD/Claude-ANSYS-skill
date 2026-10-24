# Eval: does Claude solve real engineering problems with this connector?

24 problems across static, modal, buckling, thermal, dynamics, design optimisation, CFD and engineering
judgement. Every reference answer is derived independently (`cases.py`, readable in [cases.md](cases.md)), so
the grade measures physics, not agreement with another model.

**Tiers:**
- **Advanced (16):** problems that need judgement or multi-step setup, such as moments via RBE3, free-free modes,
  lumped masses, convection fins, transient and harmonic dynamics, two-constraint sizing, a singularity trap, a
  NAFEMS benchmark, Fluent mixing, and pipe flow built from CAD. This is the default run.
- **Core (8):** single-physics warm-ups.

**How a case runs:** each case runs **real Claude Code headlessly** (`claude -p`) with this plugin loaded and
nothing else:
- tools limited to the Ansys connector and the skills
- a fresh folder and Ansys session per case
- the answer captured as structured output and graded on relative error

**Billing:**
- **Default:** your Claude subscription, with no API spend.
- **`--engine cli-api`:** billed to an API key, with a hard per-case and total dollar cap.

```
cd server
.venv\Scripts\python ..\eval\run_eval.py --self-test          # grader check, no solver, no API
.venv\Scripts\python ..\eval\run_eval.py --approve-harness    # you approve this exact runner once
.venv\Scripts\python ..\eval\run_eval.py                      # advanced tier, resumable
.venv\Scripts\python ..\eval\run_eval.py --tier all
```

The cases run one at a time because Ansys licences (especially Student) don't like parallel solvers. A full
advanced run keeps a laptop busy for a few hours.

## Status

- **Grader self-test:** passes. Reference answers score 100 %, empty or 50 %-off answers score 0 %.
- **Full run:** not published yet. Run it and open a PR with `.claude/hillclimb/ansys-solver/baseline/results.jsonl`.
- **Benchmarks:** the connector's own benchmarks (`server/tests`) pass. Every MAPDL analysis type matches theory
  within 0.7 %; Workbench-hosted Mechanical matches within 0.3 %; Fluent conserves mass and energy exactly.
- **CAD → Fluent pipe flow:** matches Poiseuille within 6 % (pressure drop) and 2 % (peak velocity) on tet meshes.
