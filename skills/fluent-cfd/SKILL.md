---
name: fluent-cfd
description: Run CFD in Ansys Fluent through the ansys connector (PyFluent). Covers loading meshes/cases, physics models, materials, boundary conditions, solving to convergence, report definitions, contour images and saving case/data, plus conservation checks. Use for fluid flow, pressure drop, flow rates, mixing, convective heat transfer, internal or external aerodynamics, or any request mentioning Fluent or CFD.
---

# CFD with Fluent

`fluent_start(mode="solver", dimension=3, processors=N, working_directory=...)` launches Fluent without a GUI. `fluent_run(code, images=[...])` executes PyFluent Python with `solver` (the session), `pyfluent` and `workdir` predefined. Variables persist between calls.

**Keep it to about 2 `fluent_run` calls:**
1. Read the mesh, set up physics and reports, initialize, iterate, and end with `rd.compute(...)`.
2. Define the contours and pass their names in `images=[...]`.

A call returns:
- printed output
- the final expression's value
- a compact transcript: the convergence verdict, warnings and errors, and the last residual row

Read those warnings: reversed flow, divergence, "Error:". Use `verbose=True` only when debugging.

## 1. Mesh or case

```python
solver.settings.file.read_case(file_name=r"C:\path\part.msh.h5")   # .msh/.msh.h5/.cas.h5
solver.settings.mesh.check()          # read the transcript: negative volumes are fatal
```
- If there's no mesh:
  - Fluent meshing: `fluent_start(mode="meshing")`, then the watertight workflow (`meshing.workflow`), then `meshing.switch_to_solver()`.
  - Or a Workbench "Fluid Flow (Fluent)" system with geometry plus meshing.
  - Keep cell counts under **1M on Ansys Student**.
- Ask what the units of the mesh are. If they aren't metres: `solver.settings.mesh.scale(x_scale=0.001, y_scale=0.001, z_scale=0.001)`.

## 2. Physics (verified on the mixing-elbow benchmark)

```python
setup = solver.settings.setup
setup.models.energy.enabled = True                       # only if heat transfer matters
setup.models.viscous.model = "k-omega"                   # SST k-omega default is a good general choice; "laminar" if Re is low
setup.materials.database.copy_by_name(type="fluid", name="water-liquid")
setup.cell_zone_conditions.fluid["<zone>"].general.material = "water-liquid"
vi = setup.boundary_conditions.velocity_inlet
vi["inlet"].momentum.velocity_magnitude.value = 0.4      # m/s
vi["inlet"].thermal.temperature.value = 293.15           # K
po = setup.boundary_conditions.pressure_outlet
po["outlet"].momentum.gauge_pressure.value = 0           # Pa
```
List names before using them:
- `list(setup.boundary_conditions.velocity_inlet.keys())`
- `setup.cell_zone_conditions.fluid.keys()`
- `solver.settings.setup.boundary_conditions.get_state()` gives the full picture.

Before solving, check the Reynolds number: Re = ρVD/μ. Laminar below about 2300 in pipes; otherwise use a turbulence model. Set turbulence intensity and hydraulic diameter at inlets if they're known.

## 3. Reports, solve, convergence

```python
rd = solver.settings.solution.report_definitions
rd.flux["mdot"] = {}
rd.flux["mdot"].boundaries = ["inlet", "outlet"]
rd.flux["mdot"].per_zone = True
rd.surface["t_out"] = {}
rd.surface["t_out"].report_type = "surface-massavg"      # also surface-areaavg, surface-max ...
rd.surface["t_out"].field = "temperature"                # "pressure", "total-pressure", "velocity-magnitude" ...
rd.surface["t_out"].surface_names = ["outlet"]
solver.settings.solution.initialization.hybrid_initialize()
solver.settings.solution.run_calculation.iterate(iter_count=300)
rd.compute(report_defs=["mdot", "t_out"])                # -> [{"mdot": [v, unit], "mdot(inlet)": ...}, {...}]
```
Converged means **all** of the following:
- Residuals are below the criteria. The transcript prints "solution is converged".
- The reported quantities of interest have stopped changing. Iterate another 50–100 and compare.
- The mass imbalance (net `mdot`) is under 0.1% of the throughput. Energy imbalance is likewise small.

If residuals stall or oscillate:
- Check mesh quality.
- Lower the under-relaxation.
- Start first-order and switch to second-order discretization.
- Check whether the flow is actually transient.

## 4. Images and files

```python
g = solver.settings.results.graphics
g.contour["temp"] = {}
g.contour["temp"].field = "temperature"
g.contour["temp"].surfaces_list = ["symmetry-xyplane"]   # a plane/symmetry/wall surface
```
Put this in the same `fluent_run` with `images=["temp"], view="front"`, and the picture comes back in that call. Look at it.

Save the case and data:
```python
solver.settings.file.write(file_type="case-data", file_name=workdir + r"\study.cas.h5")
```

## 5. Verify before reporting

1. **Conservation:** mass imbalance under 0.1%. For adiabatic mixing, the outlet mass-averaged T must equal Σ(ṁᵢTᵢ)/Σṁᵢ. The benchmark matches to 0.001%.
2. **Engineering reference:**
   - pipe pressure drop: Darcy–Weisbach with the Moody/Colebrook friction factor
   - laminar pipe: Δp = 128μLQ/(πD⁴)
   - heat transfer: Dittus–Boelter Nu = 0.023 Re^0.8 Pr^0.4
   - drag: published Cd
3. **Mesh independence:** refine globally (or adapt near gradients), re-solve, and confirm the key outputs change by less than about 2–5%.
4. **Wall treatment:** for SST k-ω, wall y+ ≈ 1 resolves the boundary layer; with wall functions use 30–300. Check with a `surface-areaavg` report of `y-plus` on walls.

## Report

- The quantities of interest with units.
- Convergence evidence: residuals, monitor flatness, imbalance.
- The reference comparison.
- Contour image(s).
- The model choices: turbulence model, materials, boundary values.
- Where the case/data files are.
