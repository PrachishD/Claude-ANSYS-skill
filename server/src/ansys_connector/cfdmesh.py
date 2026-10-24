"""Fluid-domain meshing for Fluent: STEP -> gmsh tetrahedra -> native Fluent .msh with named zones.

Fluent's CGNS importer crashes intermittently on gmsh output, so the mesh is written in Fluent's own
ASCII mesh format, which its core reader handles. Boundary faces are grouped into named zones
(velocity-inlet, pressure-outlet, wall, symmetry, ...) chosen by CAD face id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# Fluent boundary-condition type codes for face zones
BC_CODES = {"interior": 2, "wall": 3, "pressure-inlet": 4, "pressure-outlet": 5, "symmetry": 7,
            "velocity-inlet": 10, "mass-flow-inlet": 20, "outflow": 36}
# Face-zone type keywords used in the zone-name section (45)
BC_NAMES = {"wall": "wall", "pressure-inlet": "pressure-inlet", "pressure-outlet": "pressure-outlet",
            "symmetry": "symmetry", "velocity-inlet": "velocity-inlet", "mass-flow-inlet": "mass-flow-inlet",
            "outflow": "outflow"}

# Fluent face convention: the right-hand-rule normal of the node order points toward cell c0.
# Verified with Fluent mesh check (the opposite order gives negative volumes and left-handed faces).
NORMAL_TOWARD_C0 = True


@dataclass
class FluidMesh:
    nodes: np.ndarray                 # (n, 3), metres
    tets: np.ndarray                  # (e, 4) zero-based
    zones: list[dict] = field(default_factory=list)          # [{"name", "type", "tris": (t, 3)}]
    faces: list[dict] = field(default_factory=list)          # CAD face table


def mesh_fluid(step: Path, size: float, boundaries: list[dict], scale: float = 1e-3,
               wall_size: float | None = None, wall_faces: list[int] | None = None,
               growth_distance: float | None = None) -> FluidMesh:
    """Mesh the fluid solid in `step` (units: mm unless scale says otherwise) with linear tets.

    boundaries: [{"name": "inlet", "type": "velocity-inlet", "faces": [3]}, ...]; faces not listed become
    the zone "wall". wall_size/wall_faces/growth_distance refine the mesh toward walls.
    """
    import gmsh

    from .cadmesh import _face_table  # shared CAD face description

    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("fluid")
        gmsh.model.occ.importShapes(str(step))
        gmsh.model.occ.synchronize()
        vols = gmsh.model.getEntities(3)
        if len(vols) != 1:
            raise RuntimeError(f"Expected one fluid volume in the STEP file, found {len(vols)}")
        all_faces = [t for _, t in gmsh.model.getEntities(2)]
        assigned = {f for b in boundaries for f in b["faces"]}
        unknown = assigned - set(all_faces)
        if unknown:
            raise ValueError(f"Face ids {sorted(unknown)} do not exist; valid ids are {all_faces}")
        groups = [dict(b) for b in boundaries]
        rest = [f for f in all_faces if f not in assigned]
        if rest:
            groups.append({"name": "wall", "type": "wall", "faces": rest})
        for g in groups:
            if g["type"] not in BC_NAMES:
                raise ValueError(f"Boundary type {g['type']!r} not supported; use one of {sorted(BC_NAMES)}")
        gmsh.option.setNumber("Mesh.MeshSizeMax", size)
        gmsh.option.setNumber("Mesh.MeshSizeMin", (wall_size or size) / 4)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 16)
        gmsh.option.setNumber("Mesh.ElementOrder", 1)
        gmsh.option.setNumber("Mesh.Algorithm3D", 1)
        gmsh.option.setNumber("Mesh.Optimize", 1)
        if wall_size:
            walls = wall_faces or [f for g in groups if g["type"] == "wall" for f in g["faces"]]
            dist = gmsh.model.mesh.field.add("Distance")
            gmsh.model.mesh.field.setNumbers(dist, "SurfacesList", walls)
            thr = gmsh.model.mesh.field.add("Threshold")
            gmsh.model.mesh.field.setNumber(thr, "InField", dist)
            gmsh.model.mesh.field.setNumber(thr, "SizeMin", wall_size)
            gmsh.model.mesh.field.setNumber(thr, "SizeMax", size)
            gmsh.model.mesh.field.setNumber(thr, "DistMin", 0.0)
            gmsh.model.mesh.field.setNumber(thr, "DistMax", growth_distance or 5 * size)
            gmsh.model.mesh.field.setAsBackgroundMesh(thr)
        gmsh.model.mesh.generate(3)

        tags, coords, _ = gmsh.model.mesh.getNodes()
        nodes = coords.reshape(-1, 3) * scale
        index = np.full(int(tags.max()) + 1, -1, dtype=np.int64)
        index[tags.astype(np.int64)] = np.arange(len(tags))
        etypes, _, enodes = gmsh.model.mesh.getElements(3)
        tets = np.concatenate([index[n.astype(np.int64)].reshape(-1, 4) for t, n in zip(etypes, enodes) if t == 4])
        zones = []
        for g in groups:
            tris = []
            for f in g["faces"]:
                ft, _, fn = gmsh.model.mesh.getElements(2, f)
                tris += [index[n.astype(np.int64)].reshape(-1, 3) for t, n in zip(ft, fn) if t == 2]
            zones.append({"name": g["name"], "type": g["type"], "tris": np.concatenate(tris)})
        faces = _face_table(gmsh)
        return FluidMesh(nodes=nodes, tets=tets, zones=zones, faces=faces)
    finally:
        gmsh.finalize()


def _faces_of(tets: np.ndarray):
    """All tet faces (node triplets), owning cell, and the opposite node (to orient normals)."""
    loc = [(0, 1, 2, 3), (0, 1, 3, 2), (0, 2, 3, 1), (1, 2, 3, 0)]
    tri = np.vstack([tets[:, [a, b, c]] for a, b, c, _ in loc])
    opp = np.concatenate([tets[:, d] for *_, d in loc])
    cell = np.tile(np.arange(len(tets)), 4)
    return tri, cell, opp


def write_fluent_msh(mesh: FluidMesh, path: Path) -> dict:
    """Write an ASCII Fluent mesh (.msh) with one fluid cell zone and named boundary face zones."""
    nodes, tets = mesh.nodes, mesh.tets
    tri, cell, opp = _faces_of(tets)
    key = np.sort(tri, axis=1)
    order = np.lexsort(key.T[::-1])
    key, tri, cell, opp = key[order], tri[order], cell[order], opp[order]
    same = np.all(key[1:] == key[:-1], axis=1)
    first = np.ones(len(key), dtype=bool)
    first[1:] = ~same
    starts = np.flatnonzero(first)
    counts = np.diff(np.append(starts, len(key)))
    if counts.max() > 2:
        raise RuntimeError("Non-manifold mesh: a face is shared by more than two cells")

    def oriented(face_nodes, c0_opp):
        """Order nodes so the right-hand normal points toward (or away from) the c0 cell's far node."""
        a, b, c = (nodes[face_nodes[:, i]] for i in range(3))
        n = np.cross(b - a, c - a)
        toward = np.einsum("ij,ij->i", n, nodes[c0_opp] - a) > 0
        flip = toward != NORMAL_TOWARD_C0
        out = face_nodes.copy()
        out[flip] = out[flip][:, [0, 2, 1]]
        return out

    # interior faces: pairs; c0 = first cell, c1 = second
    pair = starts[counts == 2]
    int_nodes = oriented(tri[pair], opp[pair])
    int_c0, int_c1 = cell[pair] + 1, cell[pair + 1] + 1

    # boundary faces: singles, matched to the CAD zones
    single = starts[counts == 1]
    bkey = {tuple(k): i for i, k in zip(single, key[single])}
    zone_faces = []
    used = set()
    for z in mesh.zones:
        idx = []
        for t in np.sort(z["tris"], axis=1):
            i = bkey.get(tuple(t))
            if i is not None and i not in used:
                idx.append(i)
                used.add(i)
        idx = np.array(idx, dtype=np.int64)
        zone_faces.append(idx)
    leftover = np.array([i for i in single if i not in used], dtype=np.int64)
    if len(leftover):
        raise RuntimeError(f"{len(leftover)} boundary faces did not match any CAD face zone")

    n_nodes, n_cells = len(nodes), len(tets)
    n_faces = len(pair) + sum(len(z) for z in zone_faces)
    lines = ['(0 "Fluent mesh written by ansys-connector (gmsh tetrahedra)")', "(2 3)",
             f"(10 (0 1 {n_nodes:x} 0 3))", f"(12 (0 1 {n_cells:x} 0))", f"(13 (0 1 {n_faces:x} 0))",
             f"(10 (1 1 {n_nodes:x} 1 3)("]
    lines += [f"{x:.12e} {y:.12e} {z:.12e}" for x, y, z in nodes]
    lines += ["))", f"(12 (2 1 {n_cells:x} 1 2))"]  # zone 2: fluid, type 1 active, element type 2 = tet
    fid = 1
    zone_names = ["(45 (2 fluid fluid)())"]
    # interior zone id 3
    lines.append(f"(13 (3 {fid:x} {fid + len(pair) - 1:x} 2 3)(")
    for (a, b, c), c0, c1 in zip(int_nodes + 1, int_c0, int_c1):
        lines.append(f"{a:x} {b:x} {c:x} {c0:x} {c1:x}")
    lines.append("))")
    zone_names.append("(45 (3 interior default-interior)())")
    fid += len(pair)
    summary = {"interior_faces": int(len(pair))}
    for zid, (z, idx) in enumerate(zip(mesh.zones, zone_faces), start=4):
        if not len(idx):
            raise RuntimeError(f"Zone {z['name']!r} has no faces")
        fn = oriented(tri[idx], opp[idx]) + 1
        c0 = cell[idx] + 1
        lines.append(f"(13 ({zid:x} {fid:x} {fid + len(idx) - 1:x} {BC_CODES[z['type']]:x} 3)(")
        lines += [f"{a:x} {b:x} {c:x} {k:x} 0" for (a, b, c), k in zip(fn, c0)]
        lines.append("))")
        zone_names.append(f"(45 ({zid} {BC_NAMES[z['type']]} {z['name']})())")
        summary[z["name"]] = {"type": z["type"], "faces": int(len(idx))}
        fid += len(idx)
    lines += zone_names
    path.write_text("\n".join(lines) + "\n")
    return {"nodes": n_nodes, "cells": n_cells, "faces": n_faces, "zones": summary}
