---
name: dynamic-response
description: Harmonic (frequency response) and transient (time history) structural dynamics with Ansys MAPDL via the ansys connector. Use for vibration amplitude under sinusoidal excitation, frequency response functions, resonance amplification, shock, impact, sudden or time-varying loads, or dynamic stress over time.
---

# Harmonic and transient dynamics (MAPDL)

Run the modal check and the dynamic solve as few `mapdl_run` calls as possible. Put the POST26 extraction (`VGET`/`*VSCFUN` into scalars) in the same `commands` and return the scalars with `get=[...]`. Never return whole histories as text.

**Run `modal-analysis` first.** You need the natural frequencies to choose the frequency range, the time step and the end time. Density is mandatory. Define damping explicitly:
- `DMPRAT,ζ` for constant modal damping (steel structures ~0.01–0.02, bolted assemblies 0.02–0.05), or
- `ALPHAD/BETAD` for Rayleigh damping.

## Harmonic response (steady-state sinusoid)

```
F,NODE_ID,FY,-1          ! load amplitude (unit load gives a transfer function)
/SOLU
ANTYPE,HARMIC
HROPT,FULL               ! or HROPT,MSUP,nmodes after a modal solve (faster)
HARFRQ,700,950           ! frequency band (Hz) - bracket the modes of interest
NSUBST,250               ! frequency points: resolve peaks (half-power bandwidth = 2*zeta*fn)
KBC,1                    ! same amplitude at all frequencies
DMPRAT,0.02
SOLVE
FINISH
/POST26
NSOL,2,NODE_ID,U,Y
*DIM,AMP,ARRAY,250 $ *DIM,FRQ,ARRAY,250
VGET,AMP(1),2,,2         ! KCPLX=2 -> amplitude
VGET,FRQ(1),1
*VSCFUN,AMAX,MAX,AMP(1) $ *VSCFUN,IMAX,LMAX,AMP(1)
FPEAK=FRQ(IMAX)
```
- For stress at a frequency, use `/POST1` → `HRCPLX,1,isub,0` (phase 0°) or `SET,1,isub,,AMPL` for amplitudes. Then PLNSOL.
- Base excitation (shaker table): constrain the base and apply the acceleration as `ACEL`, or `D,…,UY,amplitude` with large-mass. Keep it simple; say which method you used.
- **Check point spacing:** with ζ = 0.02 at 815 Hz, the half-power bandwidth is ~33 Hz. Use at least 5–10 points across it, or `HARFRQ` clustering (`HROPT,MSUP` + `HROUT,,ON`).

## Transient (time history)

```
F,NODE_ID,FY,-100        ! applied at t>0 (KBC,1 = step)
/SOLU
ANTYPE,TRANS
TRNOPT,FULL
TINTP,0.005              ! minimal numerical damping (default HHT/Newmark)
KBC,1                    ! step load; KBC,0 ramps over the load step
TIME,0.004
DELTIM,2.5e-5            ! <= 1/(20 * highest frequency of interest)
OUTRES,NSOL,ALL          ! or OUTRES,ALL,ALL for stresses (large files)
SOLVE
```
- For load histories, use several load steps (TIME, F, SOLVE per point), or a TABLE load (`*DIM,LOADTAB,TABLE,n,1,1,TIME` and then `F,…,%LOADTAB%`).
- To start from a static preload, solve step 1 with `TIMINT,OFF`, then `TIMINT,ON`.
- Read histories in POST26 (`NSOL`, `ESOL`, `VGET`). Use `/POST1` + `SET,,,,,time` for a field at one instant.

## Verify

- **Suddenly applied constant load on an undamped structure:** peak = 2 × static deflection. The benchmark matches within 8%; higher modes and the time-integration scheme account for the gap.
- **Harmonic resonance peak:** should sit at the modal frequency (ζ shifts it slightly). Peak amplification ≈ 1/(2ζ) × static. Benchmark: peak within 2% of the analytic f1.
- **Low-frequency limit:** harmonic response well below f1 should equal the static response.
- **Time step convergence:** halving DELTIM should change peaks by less than about 2%.

## Report

- Peak response and the frequency or time it occurs at.
- Amplification relative to static.
- The damping you assumed. The answer is only as good as ζ.
- FRF or time-history values; plot them if the user wants a curve.
