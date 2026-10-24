"""Workbench: Static Structural + linked Modal systems on IGES geometry, solved in Workbench-hosted
Mechanical, checked against beam theory."""
import asyncio, json, math, os, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from harness import call, check, connector

WD = os.path.join(tempfile.gettempdir(), "ansys_connector_tests", "workbench")
os.makedirs(WD, exist_ok=True)
L, H, B, E, RHO, F = 0.1, 0.01, 0.01, 2e11, 7850.0, 100.0
IGES = os.path.join(WD, "beam.igs")

JOURNAL = r'''import json
static = GetTemplate(TemplateName="Static Structural", Solver="ANSYS").CreateSystem()
static.GetContainer(ComponentName="Geometry").SetFile(FilePath=r"__IGES__")
modal = GetTemplate(TemplateName="Modal", Solver="ANSYS").CreateSystem(
    ComponentsToShare=[static.GetComponent(Name=n) for n in ("Engineering Data", "Geometry", "Model")],
    Position="Right", RelativeTo=static)
Save(FilePath=r"__PROJECT__", Overwrite=True)
wb_script_result = json.dumps({"static": static.Name, "modal": modal.Name})
'''

MECH = r'''
import json
ExtAPI.Application.ActiveUnitSystem = MechanicalUnitSystem.StandardMKS
body = ExtAPI.DataModel.GeoData.Assemblies[0].Parts[0].Bodies[0]
def sel(face):
    s = ExtAPI.SelectionManager.CreateSelectionInfo(SelectionTypeEnum.GeometryEntities)
    s.Ids = [face.Id]
    return s
# Select relatively: Centroid is in the CAD length unit, which need not match the active unit system.
root = sel(min(body.Faces, key=lambda f: f.Centroid[0]))
tip = sel(max(body.Faces, key=lambda f: f.Centroid[0]))
Model.Mesh.ElementSize = Quantity("0.002 [m]")
st, modal = Model.Analyses[0], Model.Analyses[1]
fixed = st.AddFixedSupport()
fixed.Location = root
force = st.AddForce()
force.Location = tip
force.DefineBy = LoadDefineBy.Components
force.YComponent.Output.DiscreteValues = [Quantity("-__F__ [N]")]
uy = st.Solution.AddDirectionalDeformation()
uy.NormalOrientation = NormalOrientationType.YAxis
seqv = st.Solution.AddEquivalentStress()
modal.AnalysisSettings.MaximumModesToFind = 4
modal.AddFixedSupport().Location = root
m1 = modal.Solution.AddTotalDeformation()
m1.Mode = 1
react = st.Solution.AddForceReaction()
react.BoundaryConditionSelection = fixed
st.Solve(True)
modal.Solve(True)
st.Solution.EvaluateAllResults()
json.dumps({"reaction_y": react.YAxis.Value, "nodes": Model.Mesh.Nodes, "uy_min": uy.Minimum.Value, "seqv_max": seqv.Maximum.Value,
            "f1": m1.ReportedFrequency.Value, "status": [str(st.Solution.Status), str(modal.Solution.Status)],
            "messages": [x.DisplayString for x in ExtAPI.Application.Messages if str(x.Severity) == "Error"]})
'''

async def main():
    async with connector() as s:
        if not os.path.exists(IGES):
            await call(s, "mapdl_start", working_directory=WD)
            await call(s, "mapdl_run", commands=f"/CLEAR,NOSTART\n/PREP7\nBLOCK,0,{L},0,{H},0,{B}\nIGESOUT,beam,igs")
            await call(s, "mapdl_stop")
        print("starting Workbench...", flush=True)
        print(" ", await call(s, "workbench_start", working_directory=WD))
        systems = await call(s, "workbench_run", script=JOURNAL.replace("__IGES__", IGES).replace("__PROJECT__", os.path.join(WD, "beam.wbpj")))
        print("  systems:", systems, flush=True)
        print("  mechanical:", await call(s, "workbench_open_mechanical", system_name=systems["static"]), flush=True)
        # setup + solve + results + stress image in ONE tool call
        res = await s.call_tool("mechanical_run", {"script": MECH.replace("__L__", str(L)).replace("__F__", str(F)), "images": ["seqv"]})
        if res.is_error:
            raise RuntimeError(res.content[0].text)
        r = json.loads(res.content[0].text)
        n_images = sum(c.type == "image" for c in res.content)
        print(" ", r, "| images returned:", n_images, flush=True)
        I, A = B * H**3 / 12, B * H
        ok = check("static tip deflection (m)", -r["uy_min"], F * L**3 / (3 * E * I), 0.03)
        ok &= check("static reaction (N)", abs(r["reaction_y"]), F, 0.01)
        ok &= check("modal f1 (Hz)", r["f1"], 1.8751**2 / (2 * math.pi) * math.sqrt(E * I / (RHO * A * L**4)), 0.03)
        ok &= n_images == 1
        print(f"  [{'PASS' if n_images == 1 else 'FAIL'}] stress image returned in the same call")
        await call(s, "workbench_run", script="Save(Overwrite=True)")
        await call(s, "workbench_stop")
        print("WORKBENCH", "PASS" if ok else "FAIL", flush=True)

asyncio.run(main())
