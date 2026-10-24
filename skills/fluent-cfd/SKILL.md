---
name: fluent-cfd
description: Run CFD in Ansys Fluent through the ansys connector (PyFluent). Covers building a fluid domain from CAD and meshing it (cfd_mesh), loading meshes/cases, physics models, materials, boundary conditions, solving to convergence, report definitions, contour images and saving case/data, plus conservation checks. Use for fluid flow, pressure drop, flow rates, mixing, convective heat transfer, internal or external aerodynamics, or any request mentioning Fluent or CFD.
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

## 1. Geometry and mesh

**If the user has a mesh or case file**, read it with `solver.settings.file.read_case(file_name=...)` (`.msh`, `.msh.h5`, `.cas.h5`).

**Otherwise, build the fluid domain from CAD with `cfd_mesh`** (CadQuery; call `cad_install` once if CAD support is missing):
1. **Model the fluid, not the part:** the space the fluid fills, such as the bore of a pipe or the channel around a body (`box.cut(body)`). Units are mm.
2. **Call `cfd_mesh(script)` without boundaries.** You get the face table and a labelled picture; pick the inlet and outlet faces by type, centre and normal.
3. **Call `cfd_mesh(script, boundaries=[{"name": "inlet", "type": "velocity-inlet", "faces": [2]}, {"name": "outlet", "type": "pressure-outlet", "faces": [3]}], mesh_size=..., wall_size=...)`.** Every face you don't list becomes `wall`. The mesh is written in **metres** in Fluent's native format, with the zone names you gave.
4. **Load and check the mesh:** in `fluent_run`, call `solver.settings.file.read_case(file_name=<msh_file>)`, then `solver.settings.mesh.check()`. Negative volumes or left-handed faces are fatal.

Mesh guidance:
- Linear tets with **wall refinement**: set `wall_size` to about 1/3 of `mesh_size`, and `growth_distance` to about 2–3 wall sizes.
- There are no prism boundary layers, so laminar flow and wall-function turbulence models are fine. For y+ ≈ 1 turbulence, use Fluent meshing's watertight workflow or a Workbench Fluid Flow system instead.
- Keep cell counts under **1M on Ansys Student**.

Pitfalls the tests uncovered:
- **CGNS mesh import:** don't use it. Fluent's CGNS importer segfaults intermittently on gmsh meshes, which is why `cfd_mesh` writes native `.msh`.
- **Initialise only after the boundary types are set.** On a domain that is still all walls, hybrid initialisation can crash Fluent.
- **`report_definitions.compute` stays inactive until the solution is initialised.**
- **Mesh units:** check them before anything else. Compute the area of the inlet surface (`surface-area` report after initialising) and compare it with the CAD.

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

For low-Reynolds laminar flow, set `solver.settings.solution.methods.p_v_coupling.flow_scheme = "Coupled"` and second-order momentum. Watch the quantity you report while iterating more, not just the residuals.

Peak values: read maxima with `surface-vertexmax`. `surface-facetmax` averages over faces and under-reads peaks by a few percent.

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
   - Connector validation on a CAD → `cfd_mesh` → Fluent laminar pipe (Re = 100):
     - **Mass balance:** exact.
     - **Pressure drop:** +6 % vs Hagen–Poiseuille, on both coarse and refined meshes.
     - **Centreline velocity:** −2 %.
   - Because that pressure-drop offset didn't shrink with refinement, treat ~5 % on tet meshes as the expected agreement and say so. For tighter numbers, use a structured or prism-layer mesh.
3. **Mesh independence:** refine globally (or adapt near gradients), re-solve, and confirm the key outputs change by less than about 2–5%.
4. **Wall treatment:** for SST k-ω, wall y+ ≈ 1 resolves the boundary layer; with wall functions use 30–300. Check with a `surface-areaavg` report of `y-plus` on walls.

## Report

- The quantities of interest with units.
- Convergence evidence: residuals, monitor flatness, imbalance.
- The reference comparison.
- Contour image(s).
- The model choices: turbulence model, materials, boundary values.
- Where the case/data files are.
