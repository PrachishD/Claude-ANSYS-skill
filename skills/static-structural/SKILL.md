---
name: static-structural
description: Linear static stress, deflection, reactions and safety factor in Ansys MAPDL via the ansys connector. Use when the user wants to stress-check a part, bracket, beam, plate, shaft or assembly under loads and supports, or asks for deflection, von Mises stress or safety factor.
---

# Static structural (MAPDL)

Assume **mm, N, MPa, tonne/mm³** unless the user says otherwise. State any assumptions you make about geometry, material, supports or loads.

## One call: build, solve, extract, plot

```
mapdl_run(commands=<APDL below>, get=["NN","SVM","SVMX","SVMY","SVMZ","UMAX","RFX","RFY","RFZ","VOL"],
          plots=["/POST1\nSET,LAST\nPLNSOL,S,EQV"], working_directory=<study folder>)
```
```
FINISH
/CLEAR,NOSTART
/PREP7
BLOCK,0,100,0,10,0,10                 ! geometry: BLOCK/CYL4/CYLIND, VSBV subtract, VADD union, VGLUE
MP,EX,1,200000 $ MP,PRXY,1,0.3 $ MP,DENS,1,7.85e-9
ET,1,SOLID187                         ! 10-node tet
ESIZE,2                               ! >= 2-3 elements through the thinnest wall
VMESH,ALL
*GET,NN,NODE,0,COUNT
NSEL,S,LOC,X,0 $ D,ALL,ALL,0          ! support
ET,2,MASS21 $ R,2,1e-12,1e-12,1e-12,1e-12,1e-12,1e-12
*GET,NMAX,NODE,0,NUM,MAXD $ PILOT=NMAX+1
N,PILOT,100,5,5                       ! load point (face centroid, or offset for a lever arm)
TYPE,2 $ REAL,2 $ E,PILOT
NSEL,S,LOC,X,100 $ RBE3,PILOT,ALL,ALL ! spread total force over the face
ALLSEL $ TYPE,1
F,PILOT,FY,-500                       ! F,PILOT,MZ,... for moments
/SOLU                                 ! keep /commands on their own line (no $ chaining)
ANTYPE,STATIC
SOLVE
FINISH
/POST1
SET,LAST
ESEL,S,TYPE,,1 $ NSLE,S
NSORT,S,EQV $ *GET,SVM,SORT,0,MAX $ *GET,NVM,SORT,0,IMAX
*GET,SVMX,NODE,NVM,LOC,X $ *GET,SVMY,NODE,NVM,LOC,Y $ *GET,SVMZ,NODE,NVM,LOC,Z
NSORT,U,SUM $ *GET,UMAX,SORT,0,MAX
ETABLE,EV,VOLU $ SSUM $ *GET,VOL,SSUM,0,ITEM,EV
ALLSEL $ NSEL,S,LOC,X,0 $ ESLN,S $ FSUM
*GET,RFX,FSUM,0,ITEM,FX $ *GET,RFY,FSUM,0,ITEM,FY $ *GET,RFZ,FSUM,0,ITEM,FZ
ALLSEL
```

## Other loads and supports

- **Pressure** (positive pushes into the face): `NSEL,...` then `SF,ALL,PRES,p`.
- **Gravity −Y:** `ACEL,0,9806.65,0`. ACEL is the frame acceleration, so the sign is opposite to gravity.
- **Symmetry or frictionless face:** `D,ALL,UY,0` on that face.
- **Bolt hole:** `LOCAL,11,1,cx,cy,0` → `NSEL,S,LOC,X,r-0.01,r+0.01` → `CSYS,0`. For radial-only restraint, add `CSYS,11` → `NROTAT,ALL` → `D,ALL,UX,0` → `CSYS,0`.
- **Curved or imported faces:** select with a tolerance, e.g. `NSEL,S,LOC,X,-1e-3,1e-3`.
- **Restraint:** restrain every rigid-body motion. "Negative pivot" means it isn't.
- **Large deflection:** if deflection exceeds about 5% of the part size, rerun with `NLGEOM,ON` and `NSUBST,10,100,5`.

## Materials (mm units)

| Material | EX | PRXY | DENS | Yield |
|---|---|---|---|---|
| Steel | 200000 | 0.30 | 7.85e-9 | 250 |
| Al 6061-T6 | 68900 | 0.33 | 2.70e-9 | 276 |
| Ti-6Al-4V | 113800 | 0.342 | 4.43e-9 | 880 |
| SS 304 | 193000 | 0.29 | 8.00e-9 | 215 |
| PLA | 3500 | 0.36 | 1.24e-9 | 60 |

## Check before reporting

1. **Equilibrium:** |RFX/RFY/RFZ| = applied load. FSUM has the same sign as the load.
2. **Hand calc:** σ = Mc/I, δ = FL³/3EI, σ = F/A, Peterson Kt. More than about 2x apart needs an explanation.
3. **Singularities:** peak stress at a sharp re-entrant corner or a support edge doesn't converge. Check SVMX/Y/Z and the plot. Report the stress a little away from it, or model a fillet.
4. **Convergence:** for a number the user will act on, rerun once with ESIZE halved, with no plots, just `get`. A change under 5% means converged.
5. **Student limit:** NN must stay under 128k.

Report:
- σvm max and its location
- δ max
- safety factor = yield/σvm
- reactions
- mass = VOL×DENS×1000 kg
- the assumptions you made
- the image
