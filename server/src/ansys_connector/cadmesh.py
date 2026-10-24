"""CAD -> MAPDL mesh: STEP geometry meshed with gmsh as SOLID187 tets, every CAD face a node component.

MAPDL's IGES import cannot rebuild solids from typical CAD exports, so geometry goes
STEP -> gmsh (OpenCASCADE kernel) -> NBLOCK/EBLOCK/CMBLOCK file that MAPDL reads with /INPUT.
Face components F1..Fn let boundary conditions target CAD faces by id instead of coordinates.
"""

from __future__ import annotations


from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# MAPDL SOLID187 midside order: M(I-J) N(J-K) O(K-I) P(I-L) Q(J-L) R(K-L)
_MAPDL_EDGES = [(0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3)]


@dataclass
class MeshData:
    nodes: np.ndarray            # (n, 3) coordinates; node number = row + 1
    tets: np.ndarray             # (e, 10) zero-based node indices in MAPDL SOLID187 order
    face_nodes: dict[int, np.ndarray] = field(default_factory=dict)  # face id -> zero-based node indices
    face_tris: dict[int, np.ndarray] = field(default_factory=dict)   # face id -> (t, 3) corner indices
    faces: list[dict] = field(default_factory=list)                  # face table for the caller


def _edge_permutation(nodes: np.ndarray, tets: np.ndarray) -> list[int]:
    """Columns 4-9 of gmsh tets -> MAPDL midside order, found geometrically from straight interior edges."""
    votes = np.zeros((6, 6))
    for el in tets[: min(len(tets), 200)]:
        v = nodes[el[:4]]
        mids = nodes[el[4:10]]
        for k, (a, b) in enumerate(_MAPDL_EDGES):
            d = np.linalg.norm(mids - (v[a] + v[b]) / 2, axis=1)
            votes[k, int(np.argmin(d))] += 1
    perm = [int(np.argmax(votes[k])) for k in range(6)]
    if len(set(perm)) != 6:
        raise RuntimeError("Could not determine tet10 midside node ordering")
    return perm


def _orient(nodes: np.ndarray, tets: np.ndarray) -> np.ndarray:
    """Make every element positively oriented (swap J/K and their midsides where needed)."""
    a, b, c, d = (nodes[tets[:, i]] for i in range(4))
    vol = np.einsum("ij,ij->i", np.cross(b - a, c - a), d - a)
    neg = vol < 0
    if neg.any():
        t = tets[neg].copy()
        # swap J<->K: M(I-J)<->O(K-I), N(J-K) stays, Q(J-L)<->R(K-L)
        t[:, [1, 2, 4, 6, 8, 9]] = t[:, [2, 1, 6, 4, 9, 8]]
        tets = tets.copy()
        tets[neg] = t
    return tets


def mesh_step(step: Path, size: float, size_min: float | None = None,
              refine: list[dict] | None = None, curvature_points: int = 12) -> MeshData:
    """Mesh a STEP solid with quadratic tets. refine: [{"faces": [ids], "size": s}] local sizes."""
    import gmsh

    gmsh.initialize(interruptible=False)  # MCP tools run off the main thread; no SIGINT hook
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("part")
        gmsh.model.occ.importShapes(str(step))
        gmsh.model.occ.synchronize()
        if not gmsh.model.getEntities(3):
            raise RuntimeError("STEP file contains no solid volume")
        gmsh.option.setNumber("Mesh.MeshSizeMax", size)
        gmsh.option.setNumber("Mesh.MeshSizeMin", size_min or size / 10)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", curvature_points)  # resolve fillets and holes
        gmsh.option.setNumber("Mesh.ElementOrder", 2)
        gmsh.option.setNumber("Mesh.HighOrderOptimize", 1)
        gmsh.option.setNumber("Mesh.Algorithm3D", 1)
        if refine:
            fields = []
            for r in refine:
                f = gmsh.model.mesh.field.add("Constant")
                gmsh.model.mesh.field.setNumbers(f, "SurfacesList", [int(x) for x in r["faces"]])
                gmsh.model.mesh.field.setNumber(f, "VIn", float(r["size"]))
                gmsh.model.mesh.field.setNumber(f, "VOut", 1e22)
                fields.append(f)
            fmin = gmsh.model.mesh.field.add("Min")
            gmsh.model.mesh.field.setNumbers(fmin, "FieldsList", fields)
            gmsh.model.mesh.field.setAsBackgroundMesh(fmin)
        gmsh.model.mesh.generate(3)

        tags, coords, _ = gmsh.model.mesh.getNodes()
        nodes = coords.reshape(-1, 3)
        index = np.full(int(tags.max()) + 1, -1, dtype=np.int64)
        index[tags.astype(np.int64)] = np.arange(len(tags))

        etypes, _, enodes = gmsh.model.mesh.getElements(3)
        tet10 = [n for t, n in zip(etypes, enodes) if t == 11]
        if not tet10:
            raise RuntimeError("gmsh produced no 10-node tetrahedra")
        tets = index[np.concatenate(tet10).astype(np.int64)].reshape(-1, 10)
        perm = _edge_permutation(nodes, tets)
        tets = np.hstack([tets[:, :4], tets[:, 4:][:, perm]])
        tets = _orient(nodes, tets)

        face_nodes, face_tris = {}, {}
        for _, ftag in gmsh.model.getEntities(2):
            ntags, _, _ = gmsh.model.mesh.getNodes(2, ftag, includeBoundary=True)
            face_nodes[ftag] = index[ntags.astype(np.int64)]
            ftypes, _, fnodes = gmsh.model.mesh.getElements(2, ftag)
            tri6 = [n for t, n in zip(ftypes, fnodes) if t == 9]
            if tri6:
                face_tris[ftag] = index[np.concatenate(tri6).astype(np.int64)].reshape(-1, 6)[:, :3]
        return MeshData(nodes=nodes, tets=tets, face_nodes=face_nodes, face_tris=face_tris, faces=_face_table(gmsh))
    finally:
        gmsh.finalize()


def _face_table(gmsh) -> list[dict]:
    """Describe every CAD face of the current gmsh model: id, type, area, centre, normal or radius/axis, bbox."""
    faces = []
    for _, ftag in gmsh.model.getEntities(2):
        kind = gmsh.model.getType(2, ftag)
        area = gmsh.model.occ.getMass(2, ftag)
        cx, cy, cz = gmsh.model.occ.getCenterOfMass(2, ftag)
        lo, hi = gmsh.model.getParametrizationBounds(2, ftag)
        uv = [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2]
        info = {"id": ftag, "type": kind, "area": round(area, 3),
                "center": [round(cx, 3), round(cy, 3), round(cz, 3)]}
        normal = gmsh.model.getNormal(ftag, uv)
        if kind == "Plane":
            info["normal"] = [round(v, 3) for v in normal]
        elif kind in ("Cylinder", "Cone", "Sphere", "Torus", "BSplineSurface", "BezierSurface"):
            curv = gmsh.model.getPrincipalCurvatures(ftag, uv)
            kmax = max(abs(curv[0][0]), abs(curv[1][0]))
            if kmax > 1e-9:
                info["radius"] = round(1.0 / kmax, 3)
            if kind == "Cylinder":
                d1, d2 = np.array(curv[2][:3]), np.array(curv[3][:3])
                axis = d1 if abs(curv[0][0]) < abs(curv[1][0]) else d2
                info["axis"] = [round(float(v), 3) for v in axis]
        info["bbox"] = [round(v, 3) for v in gmsh.model.getBoundingBox(2, ftag)]
        faces.append(info)
    return faces


def _cmblock(name: str, ids: np.ndarray) -> str:
    ids = np.unique(ids)
    out = [f"CMBLOCK,{name},NODE,{len(ids):8d}", "(8i10)"]
    for i in range(0, len(ids), 8):
        out.append("".join(f"{int(v):10d}" for v in ids[i:i + 8]))
    return "\n".join(out)


def write_apdl_mesh(mesh: MeshData, path: Path, etype: int = 1, mat: int = 1) -> None:
    """Write NBLOCK/EBLOCK/CMBLOCK input for MAPDL (/PREP7, element type SOLID187)."""
    n = len(mesh.nodes)
    e = len(mesh.tets)
    lines = ["/PREP7", f"ET,{etype},SOLID187", f"NBLOCK,6,SOLID,{n:10d},{n:10d}", "(3i9,6e21.13e3)"]
    for i, (x, y, z) in enumerate(mesh.nodes, 1):
        lines.append(f"{i:9d}{0:9d}{0:9d}{x:21.13e}{y:21.13e}{z:21.13e}")
    lines += ["N,R5.3,LOC,     -1,", f"EBLOCK,19,SOLID,{e:10d},{e:10d}", "(19i9)"]
    conn = mesh.tets + 1
    for k, el in enumerate(conn, 1):
        head = [mat, etype, 1, 1, 0, 0, 0, 0, 10, 0, k]
        lines.append("".join(f"{v:9d}" for v in head + list(el[:8])))
        lines.append("".join(f"{v:9d}" for v in el[8:]))
    lines.append(f"{-1:9d}")
    for fid, ids in mesh.face_nodes.items():
        lines.append(_cmblock(f"F{fid}", ids + 1))
    lines += ["ALLSEL", f"*SET,MESH_NN,{n}", f"*SET,MESH_NE,{e}"]
    path.write_text("\n".join(lines) + "\n")


def tet_volume(mesh: MeshData) -> float:
    """Volume of the straight-sided tets (quick sanity check against the CAD volume)."""
    a, b, c, d = (mesh.nodes[mesh.tets[:, i]] for i in range(4))
    return float(np.abs(np.einsum("ij,ij->i", np.cross(b - a, c - a), d - a)).sum() / 6.0)


def render_faces(mesh: MeshData, path: Path, size: tuple[int, int] = (900, 650)) -> Path | None:
    """PNG of the part with every CAD face shaded and labelled F<id> (so faces can be picked by id)."""
    try:
        import pyvista as pv

        pv.OFF_SCREEN = True
        plotter = pv.Plotter(off_screen=True, window_size=list(size))
        plotter.set_background("white")
        rng = np.random.default_rng(7)
        labels, label_pts = [], []
        for fid, tris in mesh.face_tris.items():
            cells = np.hstack([np.full((len(tris), 1), 3), tris]).ravel()
            surf = pv.PolyData(mesh.nodes, cells).clean()
            color = 0.35 + 0.6 * rng.random(3)
            plotter.add_mesh(surf, color=color, show_edges=False, smooth_shading=False)
            centre = mesh.nodes[np.unique(tris)].mean(axis=0)
            labels.append(f"F{fid}")
            label_pts.append(centre)
        plotter.add_point_labels(np.array(label_pts), labels, font_size=11, point_size=1, shape_opacity=0.75,
                                 always_visible=True, text_color="black", shape_color="white")
        plotter.view_isometric()
        plotter.show_axes()
        plotter.screenshot(str(path))
        plotter.close()
        return path
    except Exception:
        return None


def describe_faces(faces: list[dict], limit: int = 60) -> list[dict]:
    """Compact face table, largest faces first, for the tool reply."""
    keep = sorted(faces, key=lambda f: -f["area"])[:limit]
    return sorted(keep, key=lambda f: f["id"])
