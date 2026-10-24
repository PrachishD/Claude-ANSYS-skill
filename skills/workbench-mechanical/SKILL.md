---
name: workbench-mechanical
description: Build and solve Ansys Workbench projects and drive Ansys Mechanical through the ansys connector. Covers creating analysis systems (Static Structural, Modal, Buckling, Harmonic, Transient, Thermal, Fluent), importing CAD (STEP, IGES, Parasolid), materials, meshing, boundary conditions, solving, extracting results and saving a .wbpj the user can open. Use when the user has a CAD file or a Workbench project, wants results in Mechanical, or asks for a Workbench-based analysis.
---

# Workbench + Mechanical

## Workflow

Five calls in total. Every extra call re-sends the whole conversation, so don't split these further.
1. `workbench_start(working_directory=...)`. Use `show_gui=True` only if the user wants to watch.
2. `workbench_run(journal)` creates the systems, attaches geometry and saves the project.
3. `workbench_open_mechanical(system_name)` opens Mechanical on a system. Every analysis sharing its Model appears in `Model.Analyses`.
4. `mechanical_run(script, images=["vm"])` does setup, mesh, solve and results in **one** script.
   - It ends with `json.dumps({...})`; the value of the last expression comes back.
   - `images` names result objects from the script. They come back as pictures in the same call.
5. `workbench_run('Save(Overwrite=True)')`, then `workbench_stop()`.

Licensing: under Ansys Student, standalone `mechanical_start` can mesh and script, but its solves fail with "element ... not ordered". Always solve through Workbench-hosted Mechanical.

## Workbench journal (IronPython)

Return data by assigning a JSON string to `wb_script_result`.
```python
import json
static = GetTemplate(TemplateName="Static Structural", Solver="ANSYS").CreateSystem()
static.GetContainer(ComponentName="Geometry").SetFile(FilePath=r"C:\path\part.step")   # STEP/IGES/x_t/scdocx/agdb
modal = GetTemplate(TemplateName="Modal", Solver="ANSYS").CreateSystem(
    ComponentsToShare=[static.GetComponent(Name=n) for n in ("Engineering Data", "Geometry", "Model")],
    Position="Right", RelativeTo=static)
Save(FilePath=r"C:\path\study.wbpj", Overwrite=True)
wb_script_result = json.dumps({"static": static.Name, "modal": modal.Name})   # e.g. "SYS", "SYS 1"
```
Template names: `Static Structural`, `Modal`, `Harmonic Response`, `Transient Structural`, `Eigenvalue Buckling`, `Steady-State Thermal`, `Transient Thermal`, `Random Vibration`, `Response Spectrum` (all `Solver="ANSYS"`), and `Fluid Flow` with `Solver="FLUENT"` for Fluent (open it with `workbench_open_fluent`).

Systems that share `Model` appear together in one Mechanical session. That's the easiest way to run several analysis types on one geometry and mesh.

## Mechanical scripting essentials

```python
import json
ExtAPI.Application.ActiveUnitSystem = MechanicalUnitSystem.StandardNMM   # mm, N, MPa (StandardMKS = SI)
body = ExtAPI.DataModel.GeoData.Assemblies[0].Parts[0].Bodies[0]

def sel(*entities):
    s = ExtAPI.SelectionManager.CreateSelectionInfo(SelectionTypeEnum.GeometryEntities)
    s.Ids = [e.Id for e in entities]
    return s

# Pick faces RELATIVELY (extremes, surface type, area): Centroid is in the CAD length unit,
# which need not match the active unit system - absolute coordinates silently pick wrong faces.
root = min(body.Faces, key=lambda f: f.Centroid[0])
tip  = max(body.Faces, key=lambda f: f.Centroid[0])
holes = [f for f in body.Faces if str(f.SurfaceType) == "GeoSurfaceCylinder"]

Model.Mesh.ElementSize = Quantity("2 [mm]")
Model.Mesh.GenerateMesh()

st = Model.Analyses[0]
fixed = st.AddFixedSupport(); fixed.Location = sel(root)
force = st.AddForce(); force.Location = sel(tip)
force.DefineBy = LoadDefineBy.Components
force.YComponent.Output.DiscreteValues = [Quantity("-100 [N]")]
# Pressure: p = st.AddPressure(); p.Location = sel(face); p.Magnitude.Output.DiscreteValues = [Quantity("1 [MPa]")]
# Gravity: st.AddEarthGravity()  | Bolt pretension, remote force, bearing load, displacement...: st.AddXxx()

sol = st.Solution
uy = sol.AddDirectionalDeformation(); uy.NormalOrientation = NormalOrientationType.YAxis
vm = sol.AddEquivalentStress()
react = sol.AddForceReaction(); react.BoundaryConditionSelection = fixed
st.Solve(True)
sol.EvaluateAllResults()
json.dumps({"uy_min_mm": uy.Minimum.Value, "vm_max_MPa": vm.Maximum.Value,
            "reaction_y_N": react.YAxis.Value, "status": str(sol.Status),
            "errors": [m.DisplayString for m in ExtAPI.Application.Messages if str(m.Severity) == "Error"]})
```

Gotchas:
- **Sanity-check every selection.**
  - A load and a support on the same face give a perfect reaction and zero deformation. The solve "succeeds" with a meaningless result.
  - Return `[f.Centroid for f in faces]` or face counts with your results, and confirm the loaded and supported faces differ.
  - When deformation reads exactly 0, check the selections first.
- **.NET values aren't JSON-serializable** (UInt32, Quantity, enums). Wrap them: `int(...)`, `float(q.Value)`, `str(...)`.
- **Mechanical collections are .NET lists.** Negative indexing (`[-1]`) throws `ArgumentOutOfRangeException`. Use `[x.Count - 1]` or keep references to the objects you create.
- **Keep handles to boundary conditions** (`fixed = ...`). Probes and reactions need them; child order isn't something to rely on.
- **After `Solve(True)`, check for success.** Confirm `str(sol.Status) == "Done"`, then read the Error messages from `ExtAPI.Application.Messages`. Always return those errors with your results.
- **Modal results:** `m = modal.Solution.AddTotalDeformation(); m.Mode = 1`, then `m.ReportedFrequency.Value` after solving. Set `modal.AnalysisSettings.MaximumModesToFind`.
- **`.Value` units:** values come back in the active unit system. Quantities and Quantity strings carry units explicitly; keep them explicit.

## Verify

Apply the same discipline as `ansys-simulation`:
- reactions balance the applied loads
- a hand calculation or reference
- mesh convergence (re-solve with a smaller `ElementSize` or a refinement)
- check singularities on the exported contour image

Tell the user where the project (`.wbpj`) is so they can open it in Workbench.
