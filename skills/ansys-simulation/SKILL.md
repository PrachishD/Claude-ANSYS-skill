---
name: ansys-simulation
description: Entry point for any simulation with the Ansys connector (FEA or CFD). Use it to pick the Ansys product and analysis skill, keep tool calls and tokens low, and verify results before reporting. Use whenever the user asks to simulate, analyse, mesh or solve something in Ansys (stress, deflection, vibration, buckling, heat, thermal stress, dynamics, fluid flow), or to work with a Workbench project, Mechanical model or Fluent case.
---

# Simulating with the Ansys connector

You make the engineering decisions and write the solver input. The connector only carries it to Ansys.

| Situation | Product, then skill |
|---|---|
| Geometry you can build from primitives; fast and exact | **MAPDL** (`mapdl_run`): `static-structural`, `modal-analysis`, `buckling-analysis`, `thermal-analysis`, `dynamic-response` |
| User has CAD (STEP/IGES/Parasolid) or wants a Workbench project | **Workbench + Mechanical**: `workbench-mechanical` |
| Fluid flow or CFD (with or without CAD) | **Fluent**: `fluent-cfd` (`cfd_mesh` builds the fluid mesh from CAD) |
| Optimise a design: lighter, stiffer, or meeting targets | `design-optimization` |
| Write up a finished study | `engineering-report` (`report_create`) |

## Keep it cheap: every tool call re-sends the whole conversation

- **Batch the work.** A MAPDL study should be one `mapdl_run`: model, solve, `*GET` results, `get=[...]` and `plots=[...]`. MAPDL starts automatically; don't call `mapdl_start` or `mapdl_get_parameters` separately.
  - Mechanical: put setup, solve and the JSON results in one `mechanical_run`.
  - Fluent: put setup, iterate and report in one `fluent_run`.
- **Request only what you'll use.**
  - Plot one or two images at the default size.
  - Don't ask for `verbose` output unless you're debugging an error.
  - Don't re-plot to "check".
- **Iterate in place.** A refinement or design change is a short `mapdl_run` that edits and re-solves, without plots, unless the picture matters.
- **Don't re-load skills** you've already loaded in this conversation.
- **Stop sessions at the end** (`mapdl_stop` and so on) to free the license.

## Limits

- **Ansys Student:** 128k nodes for structural and thermal; 1M cells for Fluent.
- **Standalone Mechanical can't solve under the Student license.** Use the Workbench route or MAPDL.

## Pitfalls found in testing

- **APDL:**
  - Don't chain `/`-commands with `$`; it raises a false error.
  - Restrain every rigid-body motion; "negative pivot" means something is free.
- **Lumped masses** (motors, pumps): give them realistic rotary inertia. A point mass over-predicted a sway mode by 19 %.
- **Mechanical:**
  - Pick faces relatively (min/max), because centroids are in CAD units.
  - If a support and a load share a face, you get a perfect reaction and zero deformation; check selections whenever deflection reads 0.
  - Wrap .NET values in `int()`/`str()` before `json.dumps`.
  - Never use negative indexing on Mechanical collections.
- **CAD into MAPDL:** go through `cad_build` (STEP → gmsh); MAPDL's IGES import can't rebuild solids.
- **Fluent:**
  - Build fluid meshes with `cfd_mesh` (native `.msh`), not CGNS import.
  - Set the boundary types before initialising.

## Verify before reporting

1. **Equilibrium and conservation.** Structural reactions balance the loads; thermal heat in = heat out; CFD mass imbalance under 0.1%.
2. **Hand calculation or reference** within the expected error. Explain any large gap.
3. **Mesh convergence** for numbers the user will act on. Key results should change by less than 5%.
4. **Singularities.** Peak stress at a sharp corner or a constraint edge isn't a real value.
5. **Units, materials and load directions** match what the user asked for.

Report the key numbers with units and locations, the safety factor, the checks above, your assumptions, one image, and the file locations.
