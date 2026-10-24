"""Report tool: render the motor-bracket study through MCP and check both files."""
import asyncio, json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(__file__))
from harness import connector

EX = Path(__file__).resolve().parents[2] / "examples" / "motor-bracket"
OUT = os.path.join(tempfile.gettempdir(), "ansys_connector_tests", "report")

SPEC = {
    "title": "Motor mounting bracket - static and modal check",
    "project": "Example study", "part": "L-bracket, Al 6061-T6, 6 mm plate",
    "verdict": "REVIEW",
    "summary": "The bracket carries the 500 N shock load with a safety factor of about 2.0 on yield and 0.81 mm deflection. "
               "With a realistic motor rotary inertia, mode 2 sits at 131 Hz, 9.5 % above twice running speed (120 Hz), "
               "inside the 20 % resonance band. Stiffening or a bump test is recommended before release.",
    "scope": "Linear static check under a 500 N shock load plus gravity, and modal check against 3600 rpm.",
    "geometry": "L-bracket: 80 mm base with two 8.5 mm bolt holes at X = 20 and 60 mm, 60 mm upright, 40 mm wide, 6 mm thick.",
    "material": [{"item": "Young's modulus", "value": "68900", "unit": "MPa"},
                 {"item": "Poisson's ratio", "value": "0.33"},
                 {"item": "Density", "value": "2.70e-9", "unit": "t/mm^3"},
                 {"item": "Yield strength", "value": "276", "unit": "MPa"}],
    "mesh": [{"item": "Element", "value": "SOLID187 (10-node tet)"},
             {"item": "Global / local size", "value": "2 / 1", "unit": "mm"},
             {"item": "Nodes", "value": "84k"}],
    "supports": ["Both bolt bores fully fixed; base underside free"],
    "loads": ["500 N in +X on the motor (RBE3 to 20x20 mm patch)", "Gravity -Y on bracket and 1.2 kg motor"],
    "results": [
        {"quantity": "Max von Mises (outside singular zones)", "value": "135", "unit": "MPa",
         "location": "Base top, between corner and bolt 1", "limit": "276 MPa yield", "margin": "SF 2.0", "status": "PASS"},
        {"quantity": "Max deflection", "value": "0.81", "unit": "mm", "location": "Top of upright"},
        {"quantity": "Mode 1", "value": "76.5", "unit": "Hz", "limit": "outside 48-72 / 96-144 Hz",
         "margin": "+6 % above 1x band", "status": "WARN"},
        {"quantity": "Mode 2", "value": "131.4", "unit": "Hz", "limit": "outside 96-144 Hz",
         "margin": "+9.5 % from 2x", "status": "FAIL"},
    ],
    "verification": [
        {"check": "Equilibrium, X", "expected": "500 N", "actual": "500.0 N", "status": "PASS"},
        {"check": "Equilibrium, Y (weight)", "expected": "12.6 N", "actual": "12.6 N", "status": "PASS"},
        {"check": "Hand calc, upright root bending", "expected": "~85 MPa", "actual": "78 MPa", "status": "PASS"},
        {"check": "Bolt-bore peak", "expected": "converged", "actual": "203 -> 300 MPa, rising", "status": "WARN",
         "note": "Singularity at fixed bore; excluded"},
    ],
    "convergence_quantity": "max von Mises outside singular zones",
    "convergence": [{"mesh": "coarse", "nodes": "15k", "value": "131.5 MPa"},
                    {"mesh": "1 mm local", "nodes": "87k", "value": "135.5 MPa", "change": "3.0 %"},
                    {"mesh": "0.75 mm local", "nodes": "84k", "value": "136.2 MPa", "change": "0.5 %"}],
    "images": [{"path": str(EX / "stress_vonmises.png"), "caption": "Von Mises stress, 500 N + gravity"},
               {"path": str(EX / "mode2.png"), "caption": "Mode 2 (point-mass run)"}],
    "assumptions": ["Motor rotary inertia 1 t*mm^2 (80 mm diameter motor)", "Bolt bores fully fixed"],
    "limitations": ["Stresses at the bolt holes are not meaningful with fixed bores",
                    "Shock treated as static; pulses shorter than ~11 ms may amplify up to 2x"],
    "conclusions": ["Static strength adequate (SF 2.0)", "Mode 2 too close to 2x running speed"],
    "recommendations": ["Add a corner gusset or thicken the upright, then re-check mode 2", "Bump-test the prototype"],
    "files": [{"item": "APDL model", "value": "examples/motor-bracket/bracket.mac"}],
}


async def main():
    async with connector() as s:
        r = await s.call_tool("report_create", {"spec": SPEC, "output_dir": OUT, "filename": "motor_bracket_report"})
        text = r.content[0].text
        print("is_error:", r.is_error, "|", text[:400])
        out = json.loads(text)
        html = Path(out["files"]["html"]).read_text(encoding="utf-8")
        docx_kb = Path(out["files"]["docx"]).stat().st_size // 1024
        ok = (not r.is_error and docx_kb > 20 and html.count("data:image/png;base64") == 2
              and out["checks"] == {"PASS": 3, "WARN": 1, "FAIL": 0} and "REVIEW" in html)
        print("html KB:", len(html) // 1024, "| docx KB:", docx_kb)
        print("REPORT", "PASS" if ok else "FAIL")


asyncio.run(main())
