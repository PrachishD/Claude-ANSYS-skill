# Lessons from testing

Every item below was hit during real runs against Ansys 2026 R1 (Student). Each was fixed in the connector
or written into the skills Claude follows. They're also a useful checklist for anyone automating Ansys.

## Mechanical APDL

| Symptom | Cause | Handling |
|---|---|---|
| A solve that worked reports an "APDL error" | Slash commands chained with `$` (`/SOLU $ SOLVE`) trip PyMAPDL's error scan | Skills keep `/`-commands on their own line; a test runs the skill example verbatim |
| "Large negative pivot" | Rigid-body motion left free (a bar pinned on one edge can still rotate about it) | 3-2-1 minimal restraint pattern in `thermal-analysis` |
| Reasonable-looking "no resonance" verdict that was wrong | Motor modelled as a point mass with zero rotary inertia (sway mode 156 Hz vs 131 Hz with realistic inertia) | `modal-analysis` requires realistic inertia, with formulas; the example documents it |
| Stress keeps rising with mesh refinement | Singularity at a sharp corner or fully fixed bore | Skills report converged values away from singular zones; the eval includes a trap case |
| MAPDL can't build a solid from CAD IGES | IGES from OpenCASCADE arrives as loose surfaces | `cad_build` goes STEP → gmsh quadratic tets → NBLOCK/EBLOCK with every CAD face as a component |

## Mechanical and Workbench

| Symptom | Cause | Handling |
|---|---|---|
| Solve fails: "element ... not ordered" | Standalone Mechanical picks a licence product Ansys Student lacks | Skills solve through Workbench-hosted Mechanical, which works |
| Perfect reaction force, zero deformation | Load and support landed on the same face: centroids come back in CAD units, so an absolute-coordinate selection picked the wrong face | Select faces relatively (min/max, type, radius); skill tells Claude to check selections when deflection is 0 |
| `ArgumentOutOfRangeException` | `[-1]` on a .NET collection | Skill: keep references, never negative-index |
| `UInt32 is not JSON serializable` | .NET values in `json.dumps` | Skill: wrap in `int()`/`str()` |
| Workbench keeps running and holding a licence after a client crash | Launched through WMI, it escapes the MCP client's kill-on-close job | Connector launches Workbench as its own child process; a cleanup test proves it |

## Fluent and CFD

| Symptom | Cause | Handling |
|---|---|---|
| Fluent segfaults on mesh import (intermittent) | CGNS import crashes on gmsh meshes | `cfd_mesh` writes Fluent's native `.msh` with named zones (face orientation verified with Fluent's mesh check) |
| Boundary zones named `3_s_1`, all walls | CGNS physical names are lost | Native `.msh` carries `inlet`/`outlet`/`wall` and their types |
| Crash at initialisation | Hybrid initialisation on a domain that is still all walls | Skill: set boundary types first |
| `report_definitions.compute is inactive` | Reports need an initialised solution | Skill: initialise before computing reports |
| "Error: object is not active" in the transcript | Picture-resolution settings don't exist without a GUI | Connector sets them only when active |
| Peak velocity a few percent low | `surface-facetmax` averages over faces | Skill: use `surface-vertexmax` |
| Laminar pipe Δp +6 % on two mesh sizes | Tet-mesh discretisation of the developing laminar profile | Documented as expected agreement; prism layers or structured meshes for tighter numbers |

## Process and cost

| Symptom | Cause | Handling |
|---|---|---|
| A simple modal study used 22 tool calls | Every call re-sends the conversation; one call per step | `mapdl_run` builds, solves, returns values and plots in one call; Mechanical and Fluent return images in the same call |
| Huge tool replies | Raw solver echo and per-iteration residual tables | Replies carry errors, warnings and requested values; Fluent transcript cut to the verdict |
| `signal only works in main thread` | gmsh installs a Ctrl-C handler; MCP tools run on worker threads | `gmsh.initialize(interruptible=False)` |
| Install breaks on Windows | 260-character path limit inside dependencies | README: short clone path or long-path support |
