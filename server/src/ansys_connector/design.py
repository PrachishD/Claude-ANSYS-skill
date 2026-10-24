"""CAD and design-study tools: CadQuery geometry -> gmsh mesh -> MAPDL, evaluated in batches.

cad_build turns a parametric CadQuery script into STEP + an MAPDL mesh with every CAD face
as a node component (F<id>). design_evaluate runs many design variants in ONE tool call and
keeps a study history, so an optimisation loop costs a handful of round trips.
"""

from __future__ import annotations

import csv
import json
import math
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from mcp.server.mcpserver import Image

from . import mapdl
from .common import default_workdir, lock, quiet_stdout, tool

_INSTALL_HINT = (
    "CAD support is not installed. Call cad_install once (downloads CadQuery and gmsh, ~1-3 min), "
    "or run `uv sync --extra cad` in the connector's server folder."
)
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
_CONSTRAINT = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*(<=|>=|<|>|==)\s*([-+]?[\d.]+(?:[eE][-+]?\d+)?)\s*$")


def _require_cad():
    import importlib.util

    if not (importlib.util.find_spec("cadquery") and importlib.util.find_spec("gmsh")):
        raise RuntimeError(_INSTALL_HINT)


def _run_cad(script: str, params: dict):
    """Execute a CadQuery script; it must assign the final part to `result`."""
    import cadquery as cq

    ns = {"cq": cq, "math": math, "params": dict(params), **params}
    exec(compile(script, "<cad_script>", "exec"), ns)
    result = ns.get("result")
    if result is None:
        raise RuntimeError("The CAD script must assign the final solid to a variable named `result`.")
    shape = result.val() if hasattr(result, "val") else result
    solids = shape.Solids() if hasattr(shape, "Solids") else []
    if len(solids) != 1:
        raise RuntimeError(f"Expected exactly one solid, got {len(solids)}. Union the bodies or fix the script.")
    return cq, result, solids[0]


def _build(script: str, params: dict, folder: Path, stem: str, mesh_size: float,
           refine: list[dict] | None, preview: bool):
    from .cadmesh import describe_faces, mesh_step, render_faces, tet_volume, write_apdl_mesh

    cq, result, solid = _run_cad(script, params)
    folder.mkdir(parents=True, exist_ok=True)
    step = folder / f"{stem}.step"
    cq.exporters.export(result, str(step))
    mesh = mesh_step(step, size=mesh_size, refine=refine)
    mesh_file = folder / f"{stem}_mesh.inp"
    write_apdl_mesh(mesh, mesh_file)
    bb = solid.BoundingBox()
    info = {
        "step_file": str(step),
        "mesh_file": str(mesh_file),
        "apdl_load": f"/INPUT,'{mesh_file.with_suffix('')}','inp'",
        "volume": round(solid.Volume(), 3),
        "mesh_volume_check": round(tet_volume(mesh), 3),
        "bbox": [round(v, 3) for v in (bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax)],
        "nodes": int(len(mesh.nodes)),
        "elements": int(len(mesh.tets)),
        "faces": describe_faces(mesh.faces),
        "face_signature": sorted(f["type"] for f in mesh.faces),
    }
    image = render_faces(mesh, folder / f"{stem}_faces.png") if preview else None
    return info, image


@tool
def cad_install() -> str:
    """Install the optional CAD stack (CadQuery + gmsh) into the connector's environment. One-time, ~1-3 min."""
    uv = shutil.which("uv")
    cmd = [uv, "pip", "install", "--python", sys.executable, "cadquery>=2.5", "gmsh>=4.11"] if uv else \
          [sys.executable, "-m", "pip", "install", "cadquery>=2.5", "gmsh>=4.11"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        raise RuntimeError("Install failed:\n" + (proc.stderr or proc.stdout)[-2000:])
    return "CadQuery and gmsh installed. CAD tools are ready (restart not needed)."


@tool
def cad_build(script: str, name: str = "part", params: dict[str, float] | None = None,
              mesh_size: float = 3.0, refine: list[dict] | None = None,
              working_directory: str | None = None, preview: bool = True) -> list:
    """Build a part from a CadQuery script, export STEP, mesh it for MAPDL and label every CAD face.

    The script runs with `cq`, `math` and each entry of `params` as a variable; it must assign
    the final solid to `result` (units: mm). Returns volume, bbox, mesh size and a face table
    (id, type, area, center, normal or radius/axis, bbox) plus a picture with F<id> labels.
    Load into MAPDL with the returned `apdl_load` line in mapdl_run; every CAD face is then a
    node component F<id> (e.g. `CMSEL,S,F7` -> `D,ALL,ALL,0`). Element type 1 = SOLID187, MAT 1.

    Args:
        refine: local mesh sizes, e.g. [{"faces": [7, 8], "size": 0.8}] for bolt holes or fillets.
    """
    _require_cad()
    folder = Path(working_directory) if working_directory else default_workdir("cad")
    with lock, quiet_stdout():
        info, image = _build(script, params or {}, folder, name, mesh_size, refine, preview)
    info.pop("face_signature")
    out: list = [json.dumps(info)]
    if image:
        out.append(Image(path=str(image)))
    return out


FLUENT_STUDENT_CELL_LIMIT = 1_000_000


@tool
def cfd_mesh(script: str, boundaries: list[dict] | None = None, name: str = "fluid",
             params: dict[str, float] | None = None, mesh_size: float = 2.0, wall_size: float | None = None,
             growth_distance: float | None = None, working_directory: str | None = None) -> list:
    """Build a FLUID domain from a CadQuery script and mesh it for Fluent (native .msh, named zones).

    The script must assign the fluid region (the space the fluid occupies, not the pipe wall) to
    `result`, in mm. Two-step use:
      1. call without `boundaries` -> face table + labelled picture, to pick face ids;
      2. call with boundaries, e.g. [{"name": "inlet", "type": "velocity-inlet", "faces": [2]},
         {"name": "outlet", "type": "pressure-outlet", "faces": [3]}]; every other face becomes "wall".
    Types: velocity-inlet, pressure-inlet, mass-flow-inlet, pressure-outlet, outflow, wall, symmetry.
    The mesh is written in metres with linear tetrahedra; use wall_size (+ growth_distance, mm) to
    refine toward walls. Load it in fluent_run with solver.settings.file.read_case(file_name=<msh_file>).
    """
    _require_cad()
    from .cadmesh import describe_faces, mesh_step, render_faces
    from .cfdmesh import mesh_fluid, write_fluent_msh

    folder = Path(working_directory) if working_directory else default_workdir("cfd")
    folder.mkdir(parents=True, exist_ok=True)
    with lock, quiet_stdout():
        cq, result, solid = _run_cad(script, params or {})
        step = folder / f"{name}.step"
        cq.exporters.export(result, str(step))
        out: dict = {"step_file": str(step), "volume_mm3": round(solid.Volume(), 3)}
        if not boundaries:
            preview_mesh = mesh_step(step, size=mesh_size * 2)
            out["faces"] = describe_faces(preview_mesh.faces)
            out["next"] = "Call cfd_mesh again with `boundaries` naming the inlet/outlet faces by id."
            image = render_faces(preview_mesh, folder / f"{name}_faces.png")
            content: list = [json.dumps(out)]
            if image:
                content.append(Image(path=str(image)))
            return content
        mesh = mesh_fluid(step, size=mesh_size, boundaries=boundaries, scale=1e-3,
                          wall_size=wall_size, growth_distance=growth_distance)
        msh = folder / f"{name}.msh"
        info = write_fluent_msh(mesh, msh)
    out.update({"msh_file": str(msh), "units": "m", **info,
                "load": f'solver.settings.file.read_case(file_name=r"{msh}")'})
    if info["cells"] > FLUENT_STUDENT_CELL_LIMIT:
        out["warning"] = f"{info['cells']:,} cells exceeds the Ansys Student Fluent limit (1M); coarsen the mesh."
    return [json.dumps(out)]


def _check(constraints: list[str], values: dict) -> tuple[bool, list[str]]:
    violated = []
    for c in constraints:
        m = _CONSTRAINT.match(c)
        if not m:
            raise ValueError(f"Constraint {c!r} must look like 'NAME <= 123' (one name, one number)")
        name, op, num = m.group(1).upper(), m.group(2), float(m.group(3))
        v = values.get(name)
        ok = v is not None and {"<=": v <= num, ">=": v >= num, "<": v < num, ">": v > num, "==": v == num}[op]
        if not ok:
            violated.append(c)
    return not violated, violated


def _plot(rows: list[dict], objective: str, minimize: bool, path: Path) -> Path | None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        xs = [r["eval"] for r in rows if r.get(objective) is not None]
        if not xs:
            return None
        fig, ax = plt.subplots(figsize=(7.5, 4.2), dpi=110)
        feas = [(r["eval"], r[objective]) for r in rows if r.get(objective) is not None and r["feasible"]]
        infe = [(r["eval"], r[objective]) for r in rows if r.get(objective) is not None and not r["feasible"]]
        if infe:
            ax.scatter(*zip(*infe), marker="x", color="#b23b3b", label="violates constraints", zorder=3)
        if feas:
            ax.scatter(*zip(*feas), color="#1f7a3d", label="feasible", zorder=3)
        best, line = None, []
        for r in rows:
            v = r.get(objective)
            if r["feasible"] and v is not None and (best is None or (v < best if minimize else v > best)):
                best = v
            line.append((r["eval"], best))
        pts = [(x, y) for x, y in line if y is not None]
        if pts:
            ax.step(*zip(*pts), where="post", color="#0f5f6b", label="best feasible so far")
        ax.set_xlabel("design evaluation")
        ax.set_ylabel(objective)
        ax.set_title(f"{'Minimise' if minimize else 'Maximise'} {objective}")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(path)
        plt.close(fig)
        return path
    except Exception:
        return None


@tool
def design_evaluate(
    designs: list[dict[str, float]],
    apdl: str,
    outputs: list[str],
    cad_script: str | None = None,
    study: str = "study",
    objective: str | None = None,
    minimize: bool = True,
    constraints: list[str] | None = None,
    mesh_size: float = 3.0,
    refine: list[dict] | None = None,
    working_directory: str | None = None,
) -> list:
    """Evaluate a batch of design variants in ONE call (CAD -> mesh -> MAPDL -> outputs) and track the study.

    For each design (a dict of parameter values):
      1. if `cad_script` is given, build that CadQuery geometry with the design's parameters,
         export STEP and load its mesh into a cleared MAPDL database (faces = components F<id>;
         CAD_VOL = solid volume in mm^3 is set as an APDL parameter);
      2. set every design parameter as an APDL parameter (names must be valid APDL names);
      3. run `apdl` (materials, supports, loads, solve, *GET of every name in `outputs`).
    Results append to <study>/history.csv across calls; constraints like "SVM <= 138" or
    "F2 >= 144" mark feasibility; `objective` (an output or parameter name) is tracked as best
    feasible so far and plotted. Face ids must stay stable across designs: if a design's face
    topology differs from the study's first design it is rejected, not silently mis-loaded.
    """
    if cad_script:
        _require_cad()
    for d in designs:
        for k in d:
            if not _NAME.match(k):
                raise ValueError(f"Design parameter {k!r} is not a valid APDL name (letters/digits/_, max 32)")
    folder = (Path(working_directory) if working_directory else default_workdir("studies")) / study
    folder.mkdir(parents=True, exist_ok=True)
    hist_path, sig_path = folder / "history.csv", folder / "face_signature.json"
    history: list[dict] = []
    if hist_path.exists():
        with open(hist_path, newline="") as fh:
            for r in csv.DictReader(fh):
                row = {k: (float(v) if _is_num(v) else v) for k, v in r.items()}
                row["feasible"] = r.get("feasible") == "True"
                row["eval"] = int(float(r["eval"]))
                history.append(row)
    start = len(history)
    outputs_u = [o.upper() for o in outputs]
    batch = []
    with lock, quiet_stdout():
        m = mapdl._ensure(str(folder))
        for i, design in enumerate(designs, start=start + 1):
            t0 = time.time()
            row: dict = {"eval": i, **{k.upper(): v for k, v in design.items()}}
            try:
                pre = ["FINISH", "/CLEAR,NOSTART"]
                if cad_script:
                    info, _ = _build(cad_script, design, folder, f"d{i:03d}", mesh_size, refine, preview=False)
                    sig = info["face_signature"]
                    if sig_path.exists() and json.loads(sig_path.read_text()) != sig:
                        raise RuntimeError("Face topology differs from the study's first design; face ids would not match")
                    if not sig_path.exists():
                        sig_path.write_text(json.dumps(sig))
                    pre.append(info["apdl_load"])
                    pre.append(f"CAD_VOL={info['volume']}")
                    row["CAD_VOL"] = info["volume"]
                pre += [f"{k.upper()}={float(v)!r}" for k, v in design.items()]
                m.input_strings("\n".join(pre + [apdl]))
                params = m.parameters
                for name in outputs_u:
                    val = params[name] if name in params else None
                    row[name] = float(val) if val is not None else None
                if cad_script:
                    Path(info["mesh_file"]).unlink(missing_ok=True)  # STEP is kept; meshes are large
                values = {k: v for k, v in row.items() if isinstance(v, (int, float))}
                row["feasible"], violated = _check(constraints or [], values)
                if any(row.get(o) is None for o in outputs_u):
                    row["feasible"], violated = False, violated + ["missing outputs"]
                row["violated"] = "; ".join(violated)
                row["error"] = ""
            except Exception as exc:
                row.update({"feasible": False, "violated": "", "error": str(exc).strip().splitlines()[-1][:300]})
            row["seconds"] = round(time.time() - t0, 1)
            batch.append(row)
            history.append(row)

    cols = []
    for r in history:
        for k in r:
            if k not in cols:
                cols.append(k)
    with open(hist_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(history)

    result: dict = {"study_folder": str(folder), "history_csv": str(hist_path), "evaluations_total": len(history),
                    "batch": [{k: (round(v, 6) if isinstance(v, float) else v) for k, v in r.items() if v not in ("", None)}
                              for r in batch]}
    out_img = None
    if objective:
        obj = objective.upper()
        feas = [r for r in history if r["feasible"] and isinstance(r.get(obj), (int, float))]
        if feas:
            best = min(feas, key=lambda r: r[obj]) if minimize else max(feas, key=lambda r: r[obj])
            result["best_feasible"] = {k: (round(v, 6) if isinstance(v, float) else v) for k, v in best.items()
                                       if v not in ("", None)}
            if cad_script:
                result["best_step_file"] = str(folder / f"d{int(best['eval']):03d}.step")
        out_img = _plot(history, obj, minimize, folder / "progress.png")
    content: list = [json.dumps(result)]
    if out_img:
        content.append(Image(path=str(out_img)))
    return content


def _is_num(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False
