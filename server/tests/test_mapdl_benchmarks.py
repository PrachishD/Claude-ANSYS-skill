"""MAPDL benchmarks for every analysis type the skills teach, each against a closed-form answer.

Units: mm, N, s, tonne, MPa (steel E=200000, nu=0.3, rho=7.85e-9). Thermal uses mW/mm-K units
consistent with mm-tonne-s: conductivity W/(m K) is numerically the same (N/(s K)).
"""
import asyncio, math, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(__file__))
from harness import call, check, connector

WD = os.path.join(tempfile.gettempdir(), "ansys_connector_tests", "mapdl")
E, NU, RHO = 2e5, 0.3, 7.85e-9

BEAM = """FINISH
/CLEAR,NOSTART
/PREP7
BLOCK,0,{L},0,10,0,10
MP,EX,1,200000 $ MP,PRXY,1,0.3 $ MP,DENS,1,7.85e-9
ET,1,SOLID187
ESIZE,{es}
VMESH,ALL
NSEL,S,LOC,X,0 $ D,ALL,ALL,0
NSEL,S,LOC,X,{L} $ *GET,NTIP,NODE,0,COUNT
ALLSEL
*GET,TIPN,NODE,0,NUM,MAX
NTIP_ID=NODE({L},5,5)
"""

CASES = {}

CASES["modal"] = (BEAM.format(L=100, es=2) + """
/SOLU
ANTYPE,MODAL
MODOPT,LANB,4
MXPAND,4
SOLVE
*GET,F1,MODE,1,FREQ
FINISH
""", lambda p: check("modal f1, cantilever (Hz)", p["F1"],
                     1.8751**2 / (2 * math.pi) * math.sqrt(E * (10 * 10**3 / 12) / (RHO * 100 * 100**4)), 0.02))

CASES["buckling"] = (BEAM.format(L=200, es=2.5) + """
NSEL,S,LOC,X,200 $ F,ALL,FX,-1/NTIP $ ALLSEL
/SOLU
ANTYPE,STATIC
PSTRES,ON
SOLVE
FINISH
/SOLU
ANTYPE,BUCKLE
BUCOPT,LANB,2
MXPAND,2
SOLVE
*GET,PCR,MODE,1,FREQ
FINISH
""", lambda p: check("Euler buckling load, fixed-free column (N)", p["PCR"],
                     math.pi**2 * E * (10 * 10**3 / 12) / (4 * 200**2), 0.02))

CASES["thermal_steady"] = ("""FINISH
/CLEAR,NOSTART
/PREP7
BLOCK,0,100,0,10,0,10
MP,KXX,1,50
ET,1,SOLID87
ESIZE,2
VMESH,ALL
NSEL,S,LOC,X,0 $ D,ALL,TEMP,100
NSEL,S,LOC,X,100 $ D,ALL,TEMP,0
ALLSEL
/SOLU
ANTYPE,STATIC
SOLVE
FINISH
/POST1
SET,LAST
NSEL,S,LOC,X,0 $ ESLN,S $ FSUM,,HEAT
*GET,Q,FSUM,0,ITEM,HEAT
ALLSEL
*GET,TMID,NODE,NODE(50,5,5),TEMP
""", lambda p: check("conduction heat flow, 1D bar (mW)", abs(p["Q"]), 50 * 100 * 100 / 100, 0.01)
     & check("mid-bar temperature (C)", p["TMID"], 50.0, 0.01))

CASES["thermal_stress"] = ("""FINISH
/CLEAR,NOSTART
/PREP7
BLOCK,0,100,0,10,0,10
MP,EX,1,200000 $ MP,PRXY,1,0.3 $ MP,ALPX,1,1.2e-5
ET,1,SOLID187
ESIZE,2
VMESH,ALL
NSEL,S,LOC,X,0 $ D,ALL,UX,0
NSEL,S,LOC,X,100 $ D,ALL,UX,0
NSEL,S,LOC,Y,0 $ NSEL,R,LOC,Z,0 $ D,ALL,UY,0 $ D,ALL,UZ,0
NSEL,S,LOC,Y,10 $ NSEL,R,LOC,Z,0 $ D,ALL,UZ,0     ! stops rotation about X; expansion stays free
ALLSEL
TREF,0
BF,ALL,TEMP,100
/SOLU
ANTYPE,STATIC
SOLVE
FINISH
/POST1
SET,LAST
*GET,SXMID,NODE,NODE(50,5,5),S,X
""", lambda p: check("axially restrained heated bar, sigma_x (MPa)", -p["SXMID"], E * 1.2e-5 * 100, 0.02))

CASES["harmonic"] = (BEAM.format(L=100, es=2.5) + """
F,NTIP_ID,FY,-1
/SOLU
ANTYPE,HARMIC
HROPT,FULL
HARFRQ,700,950
NSUBST,250
KBC,1
DMPRAT,0.02
SOLVE
FINISH
/POST26
NSOL,2,NTIP_ID,U,Y
*DIM,AMP,ARRAY,250 $ *DIM,FRQ,ARRAY,250
VGET,AMP(1),2,,2 $ VGET,FRQ(1),1
*VSCFUN,AMAX,MAX,AMP(1) $ *VSCFUN,IMAX,LMAX,AMP(1)
FPEAK=FRQ(IMAX)
FINISH
""", lambda p: check("harmonic resonance peak (Hz) vs analytic f1", p["FPEAK"],
                     1.8751**2 / (2 * math.pi) * math.sqrt(E * (10 * 10**3 / 12) / (RHO * 100 * 100**4)), 0.02))

CASES["transient"] = (BEAM.format(L=100, es=2.5) + """
F,NTIP_ID,FY,-100
/SOLU
ANTYPE,TRANS
TRNOPT,FULL
TINTP,0.005
KBC,1
TIME,0.004
DELTIM,2.5e-5
OUTRES,NSOL,ALL
SOLVE
FINISH
/POST26
NSOL,2,NTIP_ID,U,Y
*DIM,UYT,ARRAY,160
VGET,UYT(1),2
*VSCFUN,UYMIN,MIN,UYT(1)
FINISH
""", lambda p: check("suddenly applied load, peak tip deflection = 2x static (mm)", -p["UYMIN"],
                     2 * 100 * 100**3 / (3 * E * (10 * 10**3 / 12)), 0.08))

# The static-structural skill's APDL, verbatim from SKILL.md, so the skill can't drift from working code.
_skill = (Path(__file__).parents[2] / "skills" / "static-structural" / "SKILL.md").read_text(encoding="utf-8")
_skill_apdl = _skill.split("```\nFINISH", 1)[1].split("```", 1)[0]
CASES["static_skill_snippet"] = ("FINISH" + _skill_apdl, lambda p: check(
    "skill snippet: tip deflection, 500 N (mm)", p["UMAX"], 500 * 100**3 / (3 * E * (10 * 10**3 / 12)), 0.05)
    & check("skill snippet: reaction (N)", abs(p["RFY"]), 500, 0.01))

NAMES = {"static_skill_snippet": ["UMAX", "RFY", "SVM"], "modal": ["F1"], "buckling": ["PCR"], "thermal_steady": ["Q", "TMID"], "thermal_stress": ["SXMID"],
         "harmonic": ["FPEAK", "AMAX"], "transient": ["UYMIN"]}


async def main(selected):
    results = {}
    async with connector() as s:
        for name in selected:
            apdl, verify = CASES[name]
            print(f"- {name}", flush=True)
            try:
                out = await call(s, "mapdl_run", commands=apdl, get=NAMES[name], working_directory=WD)   # solve + results: one call
                results[name] = bool(verify(out["parameters"]))
            except Exception as exc:
                print("  EXCEPTION:", str(exc)[:1200])
                results[name] = False
        await call(s, "mapdl_stop")
    print("MAPDL BENCHMARKS:", results)
    print("ALL PASS" if all(results.values()) else "SOME FAILED")


asyncio.run(main(sys.argv[1:] or list(CASES)))
