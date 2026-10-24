---
name: buckling-analysis
description: Linear (eigenvalue) buckling loads and safety factors with Ansys MAPDL via the ansys connector, plus when to switch to nonlinear buckling. Use for columns, struts, thin walls, panels, shells, frames or anything slender under compression, or when the user asks about buckling, collapse or critical load.
---

# Buckling analysis (MAPDL)

Do it in **one call**:
- `commands`: the static prestress, the buckle solve, and `*GET,LF1,MODE,1,FREQ`.
- `get=["LF1"]`.
- `plots=["/POST1\nSET,1,1\nPLDISP,2"]`.

Eigenvalue buckling takes two solves: a prestressed static run, then the buckling eigen-solve. The eigenvalue (load multiplier) scales **all** loads in the static step.

```
! ... geometry, material, mesh, supports as in static-structural ...
! Apply the real (or a unit) load
NSEL,S,LOC,X,200
*GET,NTOP,NODE,0,COUNT
F,ALL,FX,-1/NTOP          ! unit total load -> eigenvalue = critical load in N
ALLSEL
/SOLU
ANTYPE,STATIC
PSTRES,ON                 ! store stress stiffness - required
SOLVE
FINISH
/SOLU
ANTYPE,BUCKLE
BUCOPT,LANB,3             ! first 3 buckling modes
MXPAND,3
SOLVE
*GET,LF1,MODE,1,FREQ      ! load multiplier of mode 1
FINISH
```
- Critical load = LF1 × applied load. Buckling safety factor = LF1 when the applied load is the real service load.
- Dead loads that must not be scaled (gravity, preload): eigenvalue buckling scales everything. Either iterate the live load until LF = 1, or say clearly what was scaled.
- Look at the mode: `mapdl_plot("/POST1\nSET,1,1\nPLDISP,2")`. Check it's global (Euler) or local (wall crippling) buckling, as you'd expect.

## Linear buckling is non-conservative

Real structures have imperfections, so test results typically fall 10–50% below eigenvalue predictions; thin shells can be worse. For a design value:
- Apply knock-down factors, or
- Run nonlinear buckling. Add an imperfection scaled from mode 1 (`UPGEOM,factor,1,1,file,rst` after a buckling run, in a new /PREP7), then do a static run with `NLGEOM,ON`, `NSUBST,50,500,20`, `ARCLEN,ON` (or displacement control) up to collapse. Read the peak load from the load–deflection curve (POST26).

## Verify

- **Euler column:** Pcr = π²EI/(K·L)², with K = 2 (fixed-free), 1 (pinned-pinned), 0.7 (fixed-pinned), 0.5 (fixed-fixed). The connector's benchmark (fixed-free 200×10×10 mm steel) matches within 2%.
- **Check stress:** compare the static stress at the critical load with yield. If σ at Pcr exceeds yield, the column fails by yielding first (short column). Report the lower of the two.
- **Convergence:** LF1 should be converged on refinement within about 2%.

## Report

- LF1 / critical load and the mode shape.
- The buckling safety factor.
- Whether yielding governs instead.
- The knock-down caveat.
