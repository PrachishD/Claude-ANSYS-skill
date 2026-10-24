---
name: modal-analysis
description: Natural frequencies and mode shapes with Ansys MAPDL via the ansys connector. Use when the user asks about vibration, resonance, natural or first frequency, mode shapes, or whether a part will resonate near an excitation (motor speed, rotor RPM, road or engine vibration).
---

# Modal analysis (MAPDL)

Do it in **one call**:
```
mapdl_run(commands=<model + modal solve + *GET,Fi,MODE,i,FREQ>, get=["F1","F2","F3"],
          plots=["/POST1\nSET,1,1\nPLDISP,2", "SET,1,2\nPLDISP,2"])
```
That returns the frequencies and mode shapes together. Plot only the modes you'll discuss.

Build the geometry, material and mesh as in `static-structural`. **Density is mandatory**: no DENS, no mass, no modes. Use the same boundary conditions as in service; a free-free part has six ~0 Hz rigid-body modes.

**Attached components** (motors, pumps, batteries):
- Use a MASS21 at the component's centre of gravity, tied to the mounting face with RBE3. Leave the pilot node out of the RBE3 node set.
- Give it **realistic rotary inertias**, not ~0. For a solid cylinder of mass m, radius r and length h:
  - I_axial = m·r²/2
  - I_transverse = m(3r² + h²)/12
- Units are t·mm². A 1.2 kg, Ø80 mm motor is about 1 t·mm².
- A point mass with zero inertia over-predicts the sway and twist modes. In the bracket example, it read 156 Hz where realistic inertia gives 131 Hz.
- If you must guess the inertia, say so, and show how the critical mode shifts with it.

```
/SOLU
ANTYPE,MODAL
MODOPT,LANB,6          ! Block Lanczos, first 6 modes (MODOPT,LANB,N,fmin,fmax for a band)
MXPAND,6               ! expand mode shapes so you can plot them
SOLVE
*GET,F1,MODE,1,FREQ    ! F2, F3 ... likewise
FINISH
```
- Prestressed modes (spinning or loaded parts): solve a static step with `PSTRES,ON` first, then `ANTYPE,MODAL` with `PSTRES,ON`.
- Damping doesn't change modal frequencies here. It matters in `dynamic-response`.

## Look at the mode shapes

Always look at them. Frequencies alone don't say what's moving.

```
/POST1
SET,1,1      ! mode 1  (SET,1,2 for mode 2, ...)
PLDISP,2     ! deformed + undeformed outline (displacement scale is arbitrary in modal)
```
Call `mapdl_plot("/POST1\nSET,1,1\nPLDISP,2")`. Describe each mode: "1st bending about Z", "torsion", and so on.

Modal amplitudes are mass-normalised, not physical. Never report modal displacement or stress values as real.

## Verify

- **Cantilever beam:** f1 = (1.8751²/2π)·√(EI/(ρAL⁴)).
- **Simply supported beam:** f_n = (n²π / (2L²))·√(EI/(ρA)).
- **Free-free beam:** f1 = (4.730²/2π)·√(EI/(ρAL⁴)), after six ~0 Hz rigid-body modes.
- **Spring-mass sanity check:** f = (1/2π)√(k/m), using static stiffness k = F/δ from a static run.
- **Convergence:** f1 should change less than 1–2% on refinement. Modal results converge faster than stress.
- **Mesh density:** for higher modes, each wavelength needs several elements.

The connector's benchmark (100×10×10 mm steel cantilever, SOLID187, 2 mm mesh) reproduces the beam-theory f1 = 815 Hz within 2%.

## Report

- Each frequency with its mode description.
- Any frequency within ±15–20% of a stated excitation frequency. Flag it as a resonance risk.
- The mode-shape image(s).
