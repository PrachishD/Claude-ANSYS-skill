# Eval problem set

24 engineering problems (16 advanced). Every reference
answer is derived in `cases.py` from a closed-form solution or a published benchmark. A case passes when every
reported value is within tolerance and any required flag is raised.

| id | tier | category | reference answer(s) | tolerance | derivation |
|---|---|---|---|---|---|
| S1-cantilever | core | static, basic | tip_deflection = 1.35 mm; bending_stress_x50 = 37.5 MPa | 3%; 5% | delta = F L^3 / 3EI; sigma = M c / I with M = F (L - 50) |
| S2-simply-supported | core | static, boundary-conditions | midspan_deflection = 0.5 mm | 5% | delta = F L^3 / 48EI (shear adds < 1 %) |
| S3-lame-cylinder | core | static, axisymmetric | hoop_stress_bore = 166.7 MPa; bore_displacement = 0.04917 mm | 2%; 3% | Lame: sigma_theta(ri) = p (ro^2+ri^2)/(ro^2-ri^2); u = p ri/E ((ro^2+ri^2)/(ro^2-ri^2) + nu) |
| S4-plate-hole | advanced | static, stress-concentration | peak_stress = 156.7 MPa | 5% | Heywood/Howland finite-width Kt_net = 3 - 3.14 r + 3.667 r^2 - 1.527 r^3, r = d/W; sigma_net = s W/(W-d) |
| S5-torsion | advanced | static, moments | max_shear = 63.66 MPa; twist_deg = 0.9484 deg | 3%; 4% | tau = T r / J; theta = T L / (G J) |
| S6-nafems-le1 | advanced | static, nafems, 2D | sigma_yy_D = 92.7 MPa | 4% | NAFEMS LE1 target 92.7 MPa (TNSB Rev. 3, 1990) |
| M1-cantilever-modes | core | modal, mode-identification | f1 = 90.6 Hz; f2 = 181.2 Hz | 3%; 3% | f = 1.8751^2/2pi sqrt(EI/(rho A L^4)); f1 bends about the weak axis, f2 about the strong axis (2x) |
| M2-free-free | advanced | modal, rigid-body | f1_elastic = 415.1 Hz | 3% | free-free beam: f1 = 4.7300^2/2pi sqrt(EI/(rho A L^4)); six ~0 Hz rigid modes must be skipped |
| M3-tip-mass | advanced | modal, lumped-mass | f1 = 39.18 Hz | 3% | Rayleigh: f = 1/2pi sqrt(k/(M + 0.2357 m_beam)), k = 3EI/L^3 |
| M4-clamped-plate | advanced | modal, plates | f1 = 496.7 Hz | 3% | clamped circular plate: f1 = 10.2158/(2 pi a^2) sqrt(D/(rho h)) |
| B1-pinned-column | advanced | buckling, boundary-conditions | P_cr = 6580 N | 4% | P = pi^2 EI / L^2 |
| B2-fixed-free-column | core | buckling | P_cr = 4569 N | 3% | P = pi^2 EI / (2L)^2 |
| H1-composite-wall | core | thermal, steady | heat_flow = 1000 W; T_interface = 80 C | 2%; 2% | series resistance R = L1/k1 + L2/k2; Q = dT A / R |
| H2-pin-fin | advanced | thermal, convection | heat_flow = 3.947 W; T_tip = 56.73 C | 3%; 2% | fin with adiabatic tip: Q = sqrt(hPkA) theta_b tanh(mL); theta(L) = theta_b / cosh(mL) |
| H3-lumped-cooling | advanced | thermal, transient | T_300s = 48.02 C | 2% | Bi ~ 0.001 so lumped: T = Tinf + (T0 - Tinf) exp(-t/tau), tau = rho c (D/6) / h |
| H4-thermal-stress | core | thermal, thermal-stress | axial_stress = 79.35 MPa | 3% | sigma = E alpha dT |
| D1-step-load | advanced | dynamics, transient | peak_tip_deflection = 2.7 mm | 8% | suddenly applied load: dynamic peak = 2 x static |
| D2-harmonic-resonance | advanced | dynamics, harmonic | resonant_amplitude = 0.6552 mm | 6% | mode 1 carries 97.07 % of the static tip flexibility (4/1.8751^4 x 3); X = 0.9707 delta_st / 2 zeta |
| O1-min-depth | advanced | design, optimisation | min_depth = 9.283 mm | 3% | delta = 4 F L^3 / (E b h^3) -> h = (4 F L^3 / (E b delta))^(1/3) |
| O2-shaft-sizing | advanced | design, optimisation, multi-constraint | min_diameter = 29.51 mm | 3% | strength d = 23.35 mm, stiffness d = 29.51 mm -> stiffness governs |
| J1-singular-corner | advanced | judgement, singularity | must flag: singularity | - | re-entrant sharp corner: stress is singular and grows without bound under mesh refinement |
| J2-units-metres | core | judgement, units | tip_deflection = 27 mm | 3% | mixed units: delta = F L^3 / 3EI in SI, reported in mm |
| C1-fluent-mixing-elbow | advanced | cfd, fluent | T_outlet = 296.2 K | 0.2% | adiabatic mixing energy balance with the case's mass flows (1.5538 and 0.2828 kg/s) gives 296.23 K |
| C2-pipe-from-cad | advanced | cfd, fluent, cad | dp_developed = 0.645 Pa; u_max = 0.0201 m/s | 8%; 5% | Hagen-Poiseuille over the developed 200 mm (entrance length ~0.06 Re D = 60 mm): dp = 32 mu L V / D^2, u_max = 2V. Connector validation gave +6 % / -2 % on tet meshes |

## Prompts

### S1-cantilever (core)

````text
A steel cantilever beam (E = 200 GPa, nu = 0.3) is 300 mm long with a solid rectangular section
20 mm wide (Z) and 10 mm deep (Y). The end at X = 0 is fully clamped. A total force of 50 N acts
in -Y, spread over the free-end face at X = 300 mm. Report the tip deflection magnitude (key "tip_deflection",
mm) and the maximum bending stress at the section X = 50 mm (key "bending_stress_x50", MPa, magnitude).
````

### S2-simply-supported (core)

````text
A steel beam (E = 200 GPa, nu = 0.3), 400 mm span, square section 20 x 20 mm, is simply
supported: pinned along the bottom edge line at X = 0 and on a roller along the bottom edge line at X = 400 mm
(no overhang). A 1000 N downward load acts at midspan, spread across the top surface over a 2 mm wide strip.
Report the midspan deflection of the beam's neutral axis (key "midspan_deflection", mm).
````

### S3-lame-cylinder (core)

````text
A long open-ended thick-walled steel cylinder (E = 200 GPa, nu = 0.3) has inner radius 50 mm and outer
radius 100 mm and carries an internal pressure of 100 MPa (no axial load). Report the hoop stress at the bore
(key "hoop_stress_bore", MPa) and the radial displacement of the bore (key "bore_displacement", mm).
````

### S4-plate-hole (advanced)

````text
A steel plate (E = 200 GPa, nu = 0.3), 400 mm long (X), 100 mm wide (Y), 5 mm thick, has a central
through hole of 20 mm diameter. Uniform tension of 50 MPa (gross section) is applied on both X ends. Report
the peak stress at the hole edge (key "peak_stress", MPa) - the maximum principal stress.
````

### S5-torsion (advanced)

````text
A solid circular steel shaft (E = 200 GPa, nu = 0.3), diameter 20 mm, length 200 mm, is fixed at one
end; a torque of 100 N*m is applied to the other end face. Report the maximum shear stress at the surface away
from the ends (key "max_shear", MPa) and the angle of twist of the loaded end (key "twist_deg", degrees).
````

### S6-nafems-le1 (advanced)

````text
NAFEMS benchmark LE1 (elliptic membrane), plane stress. Quarter model in the first quadrant: the outer boundary
is the ellipse (x/3.25)^2 + (y/2.75)^2 = 1 and the inner boundary is the ellipse (x/2.0)^2 + (y/1.0)^2 = 1
(dimensions in metres), thickness 0.1 m. Material E = 210 GPa, nu = 0.3. Symmetry: u_x = 0 on x = 0 and u_y = 0 on
y = 0. A uniform outward normal traction of 10 MPa acts on the outer elliptical edge. Report the direct stress sigma_yy
at point D = (2.0, 0) m on the inner edge (key "sigma_yy_D", MPa).
````

### M1-cantilever-modes (core)

````text
The steel cantilever from a standard test: 300 mm long, solid section 20 mm (Z) x 10 mm (Y), clamped
at X = 0, free at the other end. Steel E = 200 GPa, nu = 0.3, density 7850 kg/m^3. Report the two lowest natural
frequencies (keys "f1" and "f2", Hz).
````

### M2-free-free (advanced)

````text
A free-free steel bar (no supports at all), 500 mm long with a 20 x 20 mm square section.
Steel E = 200 GPa, nu = 0.3, density 7850 kg/m^3. Report the lowest elastic (non-rigid-body) natural frequency
(key "f1_elastic", Hz).
````

### M3-tip-mass (advanced)

````text
The steel cantilever 300 mm long, section 20 mm (Z) x 10 mm (Y), clamped at X = 0 (E = 200 GPa,
nu = 0.3, density 7850 kg/m^3), carries a 0.5 kg point mass rigidly attached at the centroid of its free-end face
(neglect the mass's rotary inertia). Report the fundamental natural frequency (key "f1", Hz).
````

### M4-clamped-plate (advanced)

````text
A circular steel plate of radius 100 mm and thickness 2 mm is clamped all round its edge.
Steel E = 200 GPa, nu = 0.3, density 7850 kg/m^3. Report the fundamental natural frequency (key "f1", Hz).
````

### B1-pinned-column (advanced)

````text
A steel column (E = 200 GPa, nu = 0.3), 500 mm long, 10 x 10 mm square section, is pinned at
both ends (free to rotate, ends restrained laterally; one end free to move axially). It is loaded in axial compression.
Report the critical (Euler) buckling load (key "P_cr", N).
````

### B2-fixed-free-column (core)

````text
A steel column (E = 200 GPa, nu = 0.3), 300 mm long, 10 x 10 mm square section, is fully fixed
at its base and free at the top, where an axial compressive load is applied. Report the critical buckling load
(key "P_cr", N).
````

### H1-composite-wall (core)

````text
A 50 mm x 50 mm composite wall: a 20 mm copper layer (k = 400 W/m-K) bonded to a 10 mm steel layer
(k = 50 W/m-K), in series through the thickness. The exposed copper face is held at 100 C and the exposed steel face
at 0 C; the four edges are insulated. Report the total heat flow through the wall (key "heat_flow", W) and the
interface temperature (key "T_interface", C).
````

### H2-pin-fin (advanced)

````text
A steel pin fin (k = 50 W/m-K), 10 mm diameter and 100 mm long, has its base held at 100 C. Its cylindrical
surface loses heat by convection to air at 20 C with h = 25 W/m^2-K; the tip face is insulated. Report the heat flow
through the base (key "heat_flow", W) and the tip temperature (key "T_tip", C).
````

### H3-lumped-cooling (advanced)

````text
An aluminium sphere 20 mm in diameter (k = 167 W/m-K, density 2700 kg/m^3, specific heat 896 J/kg-K) starts
uniformly at 200 C and is cooled by convection to 20 C air with h = 50 W/m^2-K over its whole surface. Report its
centre temperature after 300 s (key "T_300s", C).
````

### H4-thermal-stress (core)

````text
An aluminium bar (E = 69 GPa, nu = 0.33, alpha = 23e-6 /K), 100 mm long with a 10 x 10 mm section, is held
between rigid walls at both ends so it cannot change length, but is otherwise free to expand laterally. It is heated
uniformly by 50 K from its stress-free state. Report the axial stress (key "axial_stress", MPa, as a magnitude).
````

### D1-step-load (advanced)

````text
The undamped steel cantilever 300 mm long, section 20 mm (Z) x 10 mm (Y), clamped at X = 0
(E = 200 GPa, nu = 0.3, density 7850 kg/m^3), is at rest when a constant 50 N force in -Y is suddenly applied at
t = 0, spread over the free-end face. Report the peak tip deflection magnitude during the response
(key "peak_tip_deflection", mm).
````

### D2-harmonic-resonance (advanced)

````text
The steel cantilever 300 mm long, section 20 mm (Z) x 10 mm (Y), clamped at X = 0 (E = 200 GPa,
nu = 0.3, density 7850 kg/m^3), with 2 % modal damping in every mode, is driven by a harmonic tip force of 1 N
amplitude in Y, spread over the free-end face. Report the tip displacement amplitude at the first resonance peak
(key "resonant_amplitude", mm).
````

### O1-min-depth (advanced)

````text
Size a steel cantilever (E = 200 GPa, nu = 0.3), 200 mm long, 20 mm wide, clamped at one end with a
100 N tip load spread over the free-end face. Find the minimum section depth such that the tip deflection does not
exceed 1.0 mm (key "min_depth", mm).
````

### O2-shaft-sizing (advanced)

````text
Size a solid circular steel shaft (E = 200 GPa, nu = 0.3), 500 mm long, fixed at one end, carrying a
200 N*m torque at the other. Requirements: maximum shear stress <= 80 MPa and angle of twist
<= 1.0 degree. Find the minimum diameter that meets both (key "min_diameter", mm).
````

### J1-singular-corner (advanced)

````text
An L-shaped steel bracket (E = 200 GPa, nu = 0.3): base leg 60 mm along X and upright leg 60 mm along Y, both
6 mm thick and 20 mm wide (Z), with a perfectly sharp (zero-radius) inside corner. The bottom face of the base is fully
fixed; a 200 N force in +X is spread over the top face of the upright. What is the maximum von Mises stress at the
sharp inside corner? Report it as key "corner_stress" (MPa) if you consider it meaningful.
````

### J2-units-metres (core)

````text
A steel cantilever (E = 200 GPa, nu = 0.3) is 1.2 m long with a solid 40 mm x 40 mm section, clamped at one
end, with a 2 kN transverse load spread over the free-end face. Report the tip deflection (key "tip_deflection", mm).
````

### C1-fluent-mixing-elbow (advanced)

````text
Using Fluent, solve the standard PyFluent mixing-elbow tutorial case (mesh "mixing_elbow.msh.h5" from the
PyFluent example data, folder "pyfluent/mixing_elbow"). Water (water-liquid) enters the cold inlet at 0.4 m/s and
293.15 K and the hot inlet at 1.2 m/s and 313.15 K; energy on; k-omega turbulence; pressure outlet at 0 Pa gauge.
Solve to convergence and report the mass-weighted average outlet temperature (key "T_outlet", K).
````

### C2-pipe-from-cad (advanced)

````text
Laminar pipe flow, built from scratch (no mesh is provided): a straight circular pipe of 10 mm inner
diameter and 300 mm length carries water (density 998.2 kg/m^3, viscosity 0.001003 Pa*s) entering with a uniform
velocity of 0.01005 m/s (Re = 100) and leaving at 0 Pa gauge. Create the fluid geometry, mesh it, and solve the
steady laminar flow in Fluent. Report the pressure drop between the cross-section at 100 mm from the inlet and the
outlet (key "dp_developed", Pa) and the maximum velocity at the outlet (key "u_max", m/s).
````
