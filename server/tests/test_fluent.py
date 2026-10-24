"""Fluent: mixing elbow (PyFluent tutorial mesh). Checks mass conservation and that the outlet
mass-weighted temperature matches the adiabatic mixing energy balance of the two inlets."""
import ast, asyncio, json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from harness import call, check, connector

WD = os.path.join(tempfile.gettempdir(), "ansys_connector_tests", "fluent")
os.makedirs(WD, exist_ok=True)

SETUP = r'''
from ansys.fluent.core import examples
mesh = examples.download_file("mixing_elbow.msh.h5", "pyfluent/mixing_elbow", save_path=workdir)
solver.settings.file.read_case(file_name=mesh)
setup = solver.settings.setup
setup.models.energy.enabled = True
setup.materials.database.copy_by_name(type="fluid", name="water-liquid")
setup.cell_zone_conditions.fluid["elbow-fluid"].general.material = "water-liquid"
vi = setup.boundary_conditions.velocity_inlet
for name, v, t in (("cold-inlet", 0.4, 293.15), ("hot-inlet", 1.2, 313.15)):
    vi[name].momentum.velocity_magnitude.value = v
    vi[name].thermal.temperature.value = t
rd = solver.settings.solution.report_definitions
rd.flux["mdot"] = {}
rd.flux["mdot"].boundaries = ["cold-inlet", "hot-inlet", "outlet"]
rd.flux["mdot"].per_zone = True
rd.surface["t_out"] = {}
rd.surface["t_out"].report_type = "surface-massavg"
rd.surface["t_out"].field = "temperature"
rd.surface["t_out"].surface_names = ["outlet"]
solver.settings.solution.initialization.hybrid_initialize()
solver.settings.solution.run_calculation.iterate(iter_count=250)
"solved"
'''
REPORT = r'''
import json
vals = rd.compute(report_defs=["mdot", "t_out"])
json.dumps(vals, default=str)
'''

CONTOUR = r'''
g = solver.settings.results.graphics
g.contour["temp"] = {}
g.contour["temp"].field = "temperature"
g.contour["temp"].surfaces_list = ["symmetry-xyplane"]
"contour defined"
'''


async def main():
    async with connector() as s:
        print("starting Fluent...", flush=True)
        print(" ", await call(s, "fluent_start", working_directory=WD, processors=2))
        out = await call(s, "fluent_run", code=SETUP)
        print("  setup/solve output tail:", str(out)[-600:], flush=True)
        raw = await call(s, "fluent_run", code=REPORT)
        value = ast.literal_eval(raw.split("[value]\n", 1)[1].split("\n\n", 1)[0])
        mdot, tout = json.loads(value)
        m_c, m_h, m_o = mdot["mdot(cold-inlet)"][0], mdot["mdot(hot-inlet)"][0], -mdot["mdot(outlet)"][0]
        imbalance = abs(mdot["mdot"][0]) / m_o
        print(f"  mass flows: cold {m_c:.4f}, hot {m_h:.4f}, outlet {m_o:.4f} kg/s; imbalance {100*imbalance:.4f}%")
        ok = imbalance < 1e-3
        print(f"  [{'PASS' if ok else 'FAIL'}] mass conservation (imbalance < 0.1%)")
        t_mix = (m_c * 293.15 + m_h * 313.15) / (m_c + m_h)   # constant cp, adiabatic walls
        ok &= check("outlet mass-avg temperature vs energy balance (K)", tout["t_out"][0], t_mix, 0.001)
        img = await s.call_tool("fluent_run", {"code": CONTOUR, "images": ["temp"], "view": "front"})
        n_images = sum(c.type == "image" for c in img.content)
        print(f"  [{'PASS' if n_images == 1 and not img.is_error else 'FAIL'}] contour image returned in the same call")
        ok &= n_images == 1 and not img.is_error
        await call(s, "fluent_stop")
        print("FLUENT", "PASS" if ok else "FAIL")

asyncio.run(main())
