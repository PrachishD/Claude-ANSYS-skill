---
name: thermal-analysis
description: Steady-state and transient heat conduction and thermal-stress analysis with Ansys MAPDL via the ansys connector. Use for temperature distribution, heat flow, heat sinks, conduction through parts, cooling or heating over time, convection boundaries, or stresses and distortion caused by temperature changes or thermal expansion.
---

# Thermal and thermal-stress analysis (MAPDL)

Do it in **one call**:
- `commands`: build, solve, and the `*GET`s.
- `get=[...]`.
- `plots=["/POST1\nSET,LAST\nPLNSOL,TEMP"]`.

For thermal stress, run the thermal and structural stages in the same `commands` when you can.

## Units

Use mm, tonne, s: k in W/(m·K) is numerically unchanged. Heat flow comes out in mW, heat flux in mW/mm² (= kW/m²).

| Quantity | APDL | Units (mm system) |
|---|---|---|
| Conductivity | `MP,KXX,1,k` | k in W/(m·K) |
| Specific heat | `MP,C,1,c` | c in J/(kg·K) × 1e6, i.e. mJ/(tonne·K) |
| Density | `MP,DENS,1,ρ` | tonne/mm³ |
| Film coefficient | `SF,ALL,CONV,h,T∞` | h in W/(m²·K) × 1e-3 (mW/mm²K) |

Steel: KXX 50, C 4.34e8 (434 J/kgK), DENS 7.85e-9. Aluminium: KXX 167, C 8.96e8, DENS 2.7e-9.

## Steady state

```
/PREP7
! geometry ...
MP,KXX,1,50
ET,1,SOLID87             ! 10-node thermal tet (SOLID90 for hex/20-node)
ESIZE,2 $ VMESH,ALL
NSEL,S,LOC,X,0   $ D,ALL,TEMP,100      ! fixed temperature
NSEL,S,LOC,X,100 $ SF,ALL,CONV,0.025,20  ! convection h=25 W/m2K to 20 C
NSEL,S,LOC,Y,10  $ SF,ALL,HFLUX,0.5      ! heat flux 0.5 mW/mm2 into the face
! BFE/BF,...,HGEN,q  for internal heat generation (mW/mm3)
ALLSEL
/SOLU
ANTYPE,STATIC
SOLVE
FINISH
/POST1
SET,LAST
NSORT,TEMP $ *GET,TMAX,SORT,0,MAX $ *GET,TMIN,SORT,0,MIN
NSEL,S,LOC,X,0 $ ESLN,S $ FSUM,,HEAT $ *GET,QIN,FSUM,0,ITEM,HEAT $ ALLSEL
```
Plots: `PLNSOL,TEMP`, `PLNSOL,TF,SUM` (heat flux).

## Transient

Add `MP,C` and `MP,DENS`, then:
```
/SOLU
ANTYPE,TRANS
IC,ALL,TEMP,20           ! initial temperature (or TUNIF,20)
TIME,600
DELTIM,5,1,30            ! initial, min, max step (or AUTOTS,ON)
KBC,1                    ! step-applied loads
OUTRES,ALL,ALL
SOLVE
```
Use POST26 for histories: `NSOL,2,node,TEMP` → `PRVAR,2` or `VGET` into an array.

**Time step:** keep Δt near or below ρ·c·Δx²/(k·4) for the element size Δx, or temperatures oscillate near step changes.

## Thermal stress

The simplest case is a known temperature field in the structural model:
```
MP,ALPX,1,1.2e-5         ! expansion coefficient (1/K)
TREF,20                  ! stress-free temperature
BF,ALL,TEMP,120          ! uniform temperature
! or import a thermal result: LDREAD,TEMP,,,,,thermal,rth
```
Sequential coupling:
1. Solve the thermal model (SOLID87) and save it as `thermal.rth`.
2. In /PREP7, `ETCHG,TTS` to switch to SOLID187.
3. Add the structural properties and supports.
4. `LDREAD,TEMP,LAST,,,,thermal,rth`.
5. Solve static.

Supports must not over-constrain free expansion unless that's real. Fully fixing both ends turns any temperature change into large stress (σ = EαΔT).

Supports also must not under-constrain. For a free-to-expand part, use a minimal 3-2-1 restraint: no rigid-body motion and no added stress. Pinning one edge still leaves rotation about that edge, and the solver reports a "large negative pivot".
```
NSEL,S,LOC,X,0 $ NSEL,R,LOC,Y,0 $ NSEL,R,LOC,Z,0 $ D,ALL,UX,0 $ D,ALL,UY,0 $ D,ALL,UZ,0   ! corner point: 3 DOF
NSEL,S,LOC,X,L $ NSEL,R,LOC,Y,0 $ NSEL,R,LOC,Z,0 $ D,ALL,UY,0 $ D,ALL,UZ,0               ! far corner: 2 DOF
NSEL,S,LOC,X,0 $ NSEL,R,LOC,Y,H $ NSEL,R,LOC,Z,0 $ D,ALL,UZ,0                            ! third corner: 1 DOF
ALLSEL
```

## Verify

- **1D conduction:** Q = k·A·ΔT/L, and the temperature is linear along the bar. The benchmark matches within 1%.
- **Energy balance:** heat in at fixed-temperature or flux faces must equal heat out through convection faces (FSUM,,HEAT per face group).
- **Fully restrained bar:** σ = −E·α·ΔT. The benchmark matches within 2%.
- **Lumped transient:** if Biot number hL/k < 0.1, then T(t) = T∞ + (T0−T∞)·exp(−hA·t/(ρcV)).
- **Steady state check for transients:** the final time should match a steady-state run when the end time is ≫ ρcL²/k.

## Report

- Temperature extremes and where they are.
- Heat flows and the energy balance.
- For thermal stress: peak stress, deformation, and the stress-free reference temperature you assumed.
