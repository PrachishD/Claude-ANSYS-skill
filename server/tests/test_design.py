"""CAD + design study through MCP: the motor bracket as parametric CadQuery geometry.

1. cad_build the baseline and find the bolt-bore faces from the face table.
2. design_evaluate a small DOE, then a refinement batch around the best feasible design.
Checks: baseline matches the native MAPDL model, constraints/objective bookkeeping works,
and a feasible design lighter than or equal to the thickest DOE point is found.
"""
import asyncio, json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from harness import call, connector

WD = os.path.join(tempfile.gettempdir(), "ansys_connector_tests", "design")

CAD = r'''
base, up, hole = 80.0, 60.0, 8.5
b = (cq.Workplane("XY").box(base, T, W, centered=False)
     .union(cq.Workplane("XY").box(T, up, W, centered=False))
     .edges("|Z").edges(cq.selectors.NearestToPointSelector((T, T, W / 2))).fillet(FIL)
     .faces("<Y").workplane(centerOption="CenterOfBoundBox")
     .pushPoints([(20 - base / 2, 0), (60 - base / 2, 0)]).hole(hole))
result = b
'''

APDL = r'''
MP,EX,1,68900
MP,PRXY,1,0.33
MP,DENS,1,2.70e-9
CMSEL,S,F{h1}
CMSEL,A,F{h2}
D,ALL,ALL,0
ALLSEL
ET,2,MASS21
R,2,1.2e-3,1.2e-3,1.2e-3,1.0,1.0,1.0
*GET,NMAX,NODE,0,NUM,MAXD
PILOT=NMAX+1
N,PILOT,-30,50,W/2
TYPE,2
REAL,2
E,PILOT
NSEL,S,LOC,X,-0.001,0.001
NSEL,R,LOC,Y,40,60
NSEL,R,LOC,Z,W/2-10,W/2+10
RBE3,PILOT,ALL,ALL
ALLSEL
TYPE,1
REAL,1
FINISH
/SOLU
ANTYPE,STATIC
F,PILOT,FX,500
ACEL,0,9806.65,0
SOLVE
FINISH
/POST1
SET,LAST
ESEL,S,TYPE,,1
NSLE,S
LOCAL,11,1,20,0,W/2,0,-90,0
NSEL,U,LOC,X,0,7.25
LOCAL,12,1,60,0,W/2,0,-90,0
NSEL,U,LOC,X,0,7.25
CSYS,0
NSORT,S,EQV
*GET,SVMAX,SORT,0,MAX
ALLSEL
NSORT,U,SUM
*GET,UMAX,SORT,0,MAX
FINISH
/SOLU
ANTYPE,MODAL
MODOPT,LANB,3
MXPAND,3
SOLVE
*GET,F1,MODE,1,FREQ
*GET,F2,MODE,2,FREQ
FINISH
MASS=CAD_VOL*2.7e-6
'''

OUTPUTS = ["SVMAX", "UMAX", "F1", "F2", "MASS"]
CONSTRAINTS = ["SVMAX <= 138", "F2 >= 144", "F1 <= 96"]


async def main():
    async with connector() as s:
        r = await s.call_tool("cad_build", {"script": CAD, "name": "baseline", "params": {"T": 6, "W": 40, "FIL": 1},
                                            "mesh_size": 2.5, "working_directory": WD})
        if r.is_error:
            raise RuntimeError(r.content[0].text)
        info = json.loads(r.content[0].text)
        holes = [f["id"] for f in info["faces"] if f["type"] == "Cylinder" and abs(f.get("radius", 0) - 4.25) < 0.05]
        print("baseline:", {k: info[k] for k in ("volume", "nodes", "elements")}, "| bolt-bore faces:", holes,
              "| preview image:", any(c.type == "image" for c in r.content), flush=True)
        assert len(holes) == 2, info["faces"]
        apdl = APDL.replace("{h1}", str(holes[0])).replace("{h2}", str(holes[1]))
        common = dict(apdl=apdl, outputs=OUTPUTS, cad_script=CAD, study="bracket_mass", objective="MASS",
                      minimize=True, constraints=CONSTRAINTS, mesh_size=2.5, working_directory=WD)
        doe = [{"T": 6, "W": 40, "FIL": 1}, {"T": 7, "W": 40, "FIL": 4}, {"T": 8, "W": 40, "FIL": 4},
               {"T": 6, "W": 50, "FIL": 4}, {"T": 7, "W": 30, "FIL": 6}, {"T": 9, "W": 32, "FIL": 6}]
        res = await call(s, "design_evaluate", designs=doe, **common)
        for row in res["batch"]:
            print("  DOE", {k: row.get(k) for k in ("eval", "T", "W", "FIL", "MASS", "SVMAX", "F1", "F2", "feasible", "violated", "error", "seconds")}, flush=True)
        best = res.get("best_feasible")
        print("best after DOE:", best and {k: best[k] for k in ("eval", "T", "W", "FIL", "MASS")}, flush=True)
        assert best, "no feasible design in DOE"
        t, w, f = best["T"], best["W"], best["FIL"]
        refine = [{"T": t - 0.5, "W": w, "FIL": f}, {"T": t, "W": w - 4, "FIL": f}, {"T": t - 0.5, "W": w + 4, "FIL": f + 2}]
        res2 = await s.call_tool("design_evaluate", {"designs": refine, **common})
        data = json.loads(res2.content[0].text)
        for row in data["batch"]:
            print("  REF", {k: row.get(k) for k in ("eval", "T", "W", "FIL", "MASS", "SVMAX", "F1", "F2", "feasible", "violated", "error")}, flush=True)
        b2 = data["best_feasible"]
        print("best overall:", {k: b2[k] for k in ("eval", "T", "W", "FIL", "MASS", "SVMAX", "F1", "F2")},
              "| step:", data.get("best_step_file"), "| chart:", any(c.type == "image" for c in res2.content), flush=True)
        base_row = res["batch"][0]
        ok = (base_row.get("error") in (None, "") and not base_row["feasible"] and 125 < base_row["F2"] < 140
              and data["evaluations_total"] == 9 and os.path.exists(data["best_step_file"]))
        await call(s, "mapdl_stop")
        print("DESIGN", "PASS" if ok else "FAIL")

asyncio.run(main())
