---
name: design-optimization
description: Parametric CAD and design optimisation with the Ansys connector - build real geometry in CadQuery (fillets, holes, STEP export), mesh it for MAPDL, and search design variables to minimise mass or meet stress, stiffness and frequency targets using cad_build and design_evaluate. Use when the user wants a part designed, sized, lightened, stiffened, or optimised, wants a STEP file of a design, or asks "what's the lightest/smallest X that meets Y".
---

# Design optimisation (CAD -> mesh -> MAPDL -> iterate)

If `cad_build` says CAD support isn't installed, call `cad_install` once.

## 1. Parametrise the geometry (CadQuery)

Write one CadQuery script whose design variables are plain names, such as `T`, `W` and `FIL`. Assign the final solid to `result`. Units are mm.

```python
base, up, hole = 80.0, 60.0, 8.5
b = (cq.Workplane("XY").box(base, T, W, centered=False)
     .union(cq.Workplane("XY").box(T, up, W, centered=False))
     .edges("|Z").edges(cq.selectors.NearestToPointSelector((T, T, W / 2))).fillet(FIL)
     .faces("<Y").workplane(centerOption="CenterOfBoundBox")
     .pushPoints([(20 - base / 2, 0), (60 - base / 2, 0)]).hole(hole))
result = b
```

- Model the real features that set the answer. Fillets remove fake corner singularities, so the stress you optimise is real.
- **Keep the topology fixed across the design space** (same faces in the same order). For example, keep the fillet radius above 0 rather than switching it off. `design_evaluate` rejects a design whose faces changed, because face IDs would no longer match.

Call `cad_build(script, params=<baseline>)` once:
- Look at the **face picture** and the face table.
- Pick the face IDs for supports and loads, using type, radius, axis, normal and centre. For example, bolt bores are `Cylinder` faces with radius = hole/2.
- Check that `volume` ≈ `mesh_volume_check`.

## 2. One APDL template for every design

The template runs after the mesh is loaded. Face components `F<id>`, the design parameters and `CAD_VOL` (mm³) already exist.
- **Material, supports and loads:** use `CMSEL,S,F10` → `D,ALL,ALL,0` for supports, and RBE3 or `SF` on faces for loads (as in `static-structural`).
- **Solves:** run each solve the requirements need, statics and modal in one template (`FINISH` → new `/SOLU` → `ANTYPE,MODAL` reuses the mesh and supports).
- **Outputs:** `*GET` every output named in `outputs`. Compute the objective in APDL, e.g. `MASS=CAD_VOL*2.7e-6` (kg for aluminium).
- **Stress:** exclude genuine singularities from the stress output, such as fixed bolt bores (`NSEL,U` rings with a local CS). Leave real features in.

## 3. Search in batches - few calls, many designs

```
design_evaluate(designs=[{T:6,W:40,FIL:1}, ...6-10 points...], apdl=..., outputs=["SVMAX","F1","F2","MASS"],
                cad_script=..., study="bracket_mass", objective="MASS", minimize=True,
                constraints=["SVMAX <= 138", "F2 >= 144", "F1 <= 96"])
```

1. **Explore:** include the baseline plus a spread over the variable ranges, with lows and highs mixed. About 6–10 designs per call.
2. **Read the table.** Find which variable drives each constraint, and which constraint is active at the best feasible design.
3. **Refine:** run 3–6 designs around the best feasible one, along the active constraint. For example, trade width for thickness, and shrink whatever doesn't touch the active constraint.
4. **Stop** when an improvement step gains less than ~2% on the objective, or the user's budget is reached. History accumulates in `<study>/history.csv` across calls, and the chart shows best-so-far.

Every evaluation is ~10–30 s of solver time, but only one call per batch. Don't evaluate designs one at a time.

## 4. Verify the winner before reporting

- Re-run the best design alone with a **finer mesh** (`mesh_size` about half) and confirm the outputs move by less than ~3–5%. Constraint margins thinner than the mesh error aren't margins.
- Check the drivers make sense, e.g. thicker upright → higher frequency, larger fillet → lower corner stress.
- Report:
  - the final variables, objective and every constraint with its margin
  - the baseline, and the improvement on it
  - the `best_step_file` (STEP of the winning design)
  - the progress chart
  - `engineering-report` if the user wants a write-up

State the assumptions the result depends on: boundary conditions, lumped masses and their inertia, load cases not checked.
