# Changelog

## 0.3.0

- **CFD from CAD:** `cfd_mesh` builds a fluid domain in CadQuery and meshes it with gmsh. It writes a native Fluent
  `.msh` with named inlet, outlet and wall zones. Checked against Hagen–Poiseuille pipe flow.
- **CAD for structures:** `cad_build` turns CadQuery scripts into STEP plus a quadratic-tet MAPDL mesh, with every CAD face as
  a labelled component and a picture of the face IDs.
- **Design optimisation:** `design_evaluate` runs batches of design variants in one call, with constraints, history
  and a best-so-far chart. New skill `design-optimization`; worked example `examples/bracket-optimization`.
- **Engineering reports:** `report_create` writes HTML and Word calc-sheet reports with verification tables.
  New skill `engineering-report`.
- **Eval:** 24 problems with independently derived answers. The runner drives real Claude Code headlessly with
  this plugin and grades structured answers. Advanced tier by default.
- **Skills:** a pitfalls list from testing (`docs/LESSONS.md`), lumped-mass inertia guidance, Fluent
  convergence and peak-value guidance.

## 0.2.0

- One-call MAPDL studies (`get=`, `plots=`), automatic solver start, compact tool replies, smaller images.
- Mechanical and Fluent return images in the same call.
- Workbench launched as a child process, so no orphaned licences after a crash. Watchdog for every solver.

## 0.1.0

- MAPDL, Mechanical, Fluent and Workbench connectors with verified analysis skills.
