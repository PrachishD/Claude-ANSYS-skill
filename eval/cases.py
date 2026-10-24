"""Eval cases: engineering problems with independently derived reference answers.

Every expected value is computed here from a closed-form solution (or a published
NAFEMS benchmark), so a reviewer can check each reference without running Ansys.
Units in prompts are stated explicitly; answers are graded on relative error.
"""

from __future__ import annotations

import math

# Shared material data used in the derivations (mm, N, s, tonne, MPa)
E_ST, NU_ST, RHO_ST = 200e3, 0.3, 7.85e-9
G_ST = E_ST / (2 * (1 + NU_ST))


def _cantilever_f(L, b, h, E=E_ST, rho=RHO_ST, beta=1.8751):
    I = b * h**3 / 12
    return beta**2 / (2 * math.pi) * math.sqrt(E * I / (rho * b * h * L**4))


def build() -> list[dict]:
    cases = []

    def add(cid, tags, prompt, expected, tol, units, flags=None, derivation=""):
        cases.append({"id": cid, "tags": tags, "prompt": prompt.strip(), "expected": expected, "tol": tol,
                      "units": units, "flags_required": flags or [], "derivation": derivation})

    # ------------------------------------------------------------------ static
    L, b, h, F = 300.0, 20.0, 10.0, 50.0
    I = b * h**3 / 12
    add("S1-cantilever", ["static", "basic"],
        f"""A steel cantilever beam (E = 200 GPa, nu = 0.3) is {L:.0f} mm long with a solid rectangular section
{b:.0f} mm wide (Z) and {h:.0f} mm deep (Y). The end at X = 0 is fully clamped. A total force of {F:.0f} N acts
in -Y, spread over the free-end face at X = {L:.0f} mm. Report the tip deflection magnitude (key "tip_deflection",
mm) and the maximum bending stress at the section X = 50 mm (key "bending_stress_x50", MPa, magnitude).""",
        {"tip_deflection": F * L**3 / (3 * E_ST * I), "bending_stress_x50": F * (L - 50) * (h / 2) / I},
        {"tip_deflection": 0.03, "bending_stress_x50": 0.05}, {"tip_deflection": "mm", "bending_stress_x50": "MPa"},
        derivation="delta = F L^3 / 3EI; sigma = M c / I with M = F (L - 50)")

    L2, b2, h2, F2 = 400.0, 20.0, 20.0, 1000.0
    I2 = b2 * h2**3 / 12
    add("S2-simply-supported", ["static", "boundary-conditions"],
        f"""A steel beam (E = 200 GPa, nu = 0.3), {L2:.0f} mm span, square section {b2:.0f} x {h2:.0f} mm, is simply
supported: pinned along the bottom edge line at X = 0 and on a roller along the bottom edge line at X = {L2:.0f} mm
(no overhang). A {F2:.0f} N downward load acts at midspan, spread across the top surface over a 2 mm wide strip.
Report the midspan deflection of the beam's neutral axis (key "midspan_deflection", mm).""",
        {"midspan_deflection": F2 * L2**3 / (48 * E_ST * I2)}, {"midspan_deflection": 0.05},
        {"midspan_deflection": "mm"}, derivation="delta = F L^3 / 48EI (shear adds < 1 %)")

    ri, ro, p = 50.0, 100.0, 100.0
    add("S3-lame-cylinder", ["static", "axisymmetric"],
        f"""A long open-ended thick-walled steel cylinder (E = 200 GPa, nu = 0.3) has inner radius {ri:.0f} mm and outer
radius {ro:.0f} mm and carries an internal pressure of {p:.0f} MPa (no axial load). Report the hoop stress at the bore
(key "hoop_stress_bore", MPa) and the radial displacement of the bore (key "bore_displacement", mm).""",
        {"hoop_stress_bore": p * (ro**2 + ri**2) / (ro**2 - ri**2),
         "bore_displacement": p * ri / E_ST * ((ro**2 + ri**2) / (ro**2 - ri**2) + NU_ST)},
        {"hoop_stress_bore": 0.02, "bore_displacement": 0.03}, {"hoop_stress_bore": "MPa", "bore_displacement": "mm"},
        derivation="Lame: sigma_theta(ri) = p (ro^2+ri^2)/(ro^2-ri^2); u = p ri/E ((ro^2+ri^2)/(ro^2-ri^2) + nu)")

    W, d, t, s = 100.0, 20.0, 5.0, 50.0
    r = d / W
    kt = 3 - 3.14 * r + 3.667 * r**2 - 1.527 * r**3
    add("S4-plate-hole", ["static", "stress-concentration"],
        f"""A steel plate (E = 200 GPa, nu = 0.3), 400 mm long (X), {W:.0f} mm wide (Y), {t:.0f} mm thick, has a central
through hole of {d:.0f} mm diameter. Uniform tension of {s:.0f} MPa (gross section) is applied on both X ends. Report
the peak stress at the hole edge (key "peak_stress", MPa) - the maximum principal stress.""",
        {"peak_stress": kt * s * W / (W - d)}, {"peak_stress": 0.05}, {"peak_stress": "MPa"},
        derivation="Heywood/Howland finite-width Kt_net = 3 - 3.14 r + 3.667 r^2 - 1.527 r^3, r = d/W; sigma_net = s W/(W-d)")

    dsh, Lsh, T = 20.0, 200.0, 100e3
    J = math.pi * dsh**4 / 32
    add("S5-torsion", ["static", "moments"],
        f"""A solid circular steel shaft (E = 200 GPa, nu = 0.3), diameter {dsh:.0f} mm, length {Lsh:.0f} mm, is fixed at one
end; a torque of {T/1e3:.0f} N*m is applied to the other end face. Report the maximum shear stress at the surface away
from the ends (key "max_shear", MPa) and the angle of twist of the loaded end (key "twist_deg", degrees).""",
        {"max_shear": T * (dsh / 2) / J, "twist_deg": math.degrees(T * Lsh / (G_ST * J))},
        {"max_shear": 0.03, "twist_deg": 0.04}, {"max_shear": "MPa", "twist_deg": "deg"},
        derivation="tau = T r / J; theta = T L / (G J)")

    add("S6-nafems-le1", ["static", "nafems", "2D"],
        """NAFEMS benchmark LE1 (elliptic membrane), plane stress. Quarter model in the first quadrant: the outer boundary
is the ellipse (x/3.25)^2 + (y/2.75)^2 = 1 and the inner boundary is the ellipse (x/2.0)^2 + (y/1.0)^2 = 1
(dimensions in metres), thickness 0.1 m. Material E = 210 GPa, nu = 0.3. Symmetry: u_x = 0 on x = 0 and u_y = 0 on
y = 0. A uniform outward normal traction of 10 MPa acts on the outer elliptical edge. Report the direct stress sigma_yy
at point D = (2.0, 0) m on the inner edge (key "sigma_yy_D", MPa).""",
        {"sigma_yy_D": 92.7}, {"sigma_yy_D": 0.04}, {"sigma_yy_D": "MPa"},
        derivation="NAFEMS LE1 target 92.7 MPa (TNSB Rev. 3, 1990)")

    # ------------------------------------------------------------------- modal
    add("M1-cantilever-modes", ["modal", "mode-identification"],
        f"""The steel cantilever from a standard test: {L:.0f} mm long, solid section {b:.0f} mm (Z) x {h:.0f} mm (Y), clamped
at X = 0, free at the other end. Steel E = 200 GPa, nu = 0.3, density 7850 kg/m^3. Report the two lowest natural
frequencies (keys "f1" and "f2", Hz).""",
        {"f1": _cantilever_f(L, b, h), "f2": _cantilever_f(L, h, b)}, {"f1": 0.03, "f2": 0.03}, {"f1": "Hz", "f2": "Hz"},
        derivation="f = 1.8751^2/2pi sqrt(EI/(rho A L^4)); f1 bends about the weak axis, f2 about the strong axis (2x)")

    Lf, af = 500.0, 20.0
    If = af**4 / 12
    f_free = 4.7300**2 / (2 * math.pi) * math.sqrt(E_ST * If / (RHO_ST * af * af * Lf**4))
    add("M2-free-free", ["modal", "rigid-body"],
        f"""A free-free steel bar (no supports at all), {Lf:.0f} mm long with a {af:.0f} x {af:.0f} mm square section.
Steel E = 200 GPa, nu = 0.3, density 7850 kg/m^3. Report the lowest elastic (non-rigid-body) natural frequency
(key "f1_elastic", Hz).""",
        {"f1_elastic": f_free}, {"f1_elastic": 0.03}, {"f1_elastic": "Hz"},
        derivation="free-free beam: f1 = 4.7300^2/2pi sqrt(EI/(rho A L^4)); six ~0 Hz rigid modes must be skipped")

    M_tip = 0.5e-3  # tonne
    k = 3 * E_ST * I / L**3
    m_beam = RHO_ST * L * b * h
    f_tip = math.sqrt(k / (M_tip + 0.2357 * m_beam)) / (2 * math.pi)
    add("M3-tip-mass", ["modal", "lumped-mass"],
        f"""The steel cantilever {L:.0f} mm long, section {b:.0f} mm (Z) x {h:.0f} mm (Y), clamped at X = 0 (E = 200 GPa,
nu = 0.3, density 7850 kg/m^3), carries a 0.5 kg point mass rigidly attached at the centroid of its free-end face
(neglect the mass's rotary inertia). Report the fundamental natural frequency (key "f1", Hz).""",
        {"f1": f_tip}, {"f1": 0.03}, {"f1": "Hz"},
        derivation="Rayleigh: f = 1/2pi sqrt(k/(M + 0.2357 m_beam)), k = 3EI/L^3")

    a_p, h_p = 100.0, 2.0
    Dp = E_ST * h_p**3 / (12 * (1 - NU_ST**2))
    add("M4-clamped-plate", ["modal", "plates"],
        f"""A circular steel plate of radius {a_p:.0f} mm and thickness {h_p:.0f} mm is clamped all round its edge.
Steel E = 200 GPa, nu = 0.3, density 7850 kg/m^3. Report the fundamental natural frequency (key "f1", Hz).""",
        {"f1": 10.2158 / (2 * math.pi * a_p**2) * math.sqrt(Dp / (RHO_ST * h_p))}, {"f1": 0.03}, {"f1": "Hz"},
        derivation="clamped circular plate: f1 = 10.2158/(2 pi a^2) sqrt(D/(rho h))")

    # ---------------------------------------------------------------- buckling
    Lc, ac = 500.0, 10.0
    Ic = ac**4 / 12
    add("B1-pinned-column", ["buckling", "boundary-conditions"],
        f"""A steel column (E = 200 GPa, nu = 0.3), {Lc:.0f} mm long, {ac:.0f} x {ac:.0f} mm square section, is pinned at
both ends (free to rotate, ends restrained laterally; one end free to move axially). It is loaded in axial compression.
Report the critical (Euler) buckling load (key "P_cr", N).""",
        {"P_cr": math.pi**2 * E_ST * Ic / Lc**2}, {"P_cr": 0.04}, {"P_cr": "N"}, derivation="P = pi^2 EI / L^2")

    Lc2 = 300.0
    add("B2-fixed-free-column", ["buckling"],
        f"""A steel column (E = 200 GPa, nu = 0.3), {Lc2:.0f} mm long, {ac:.0f} x {ac:.0f} mm square section, is fully fixed
at its base and free at the top, where an axial compressive load is applied. Report the critical buckling load
(key "P_cr", N).""",
        {"P_cr": math.pi**2 * E_ST * Ic / (4 * Lc2**2)}, {"P_cr": 0.03}, {"P_cr": "N"}, derivation="P = pi^2 EI / (2L)^2")

    # ----------------------------------------------------------------- thermal
    q = 100 / (0.020 / 400 + 0.010 / 50)  # W/m^2
    add("H1-composite-wall", ["thermal", "steady"],
        """A 50 mm x 50 mm composite wall: a 20 mm copper layer (k = 400 W/m-K) bonded to a 10 mm steel layer
(k = 50 W/m-K), in series through the thickness. The exposed copper face is held at 100 C and the exposed steel face
at 0 C; the four edges are insulated. Report the total heat flow through the wall (key "heat_flow", W) and the
interface temperature (key "T_interface", C).""",
        {"heat_flow": q * 0.05 * 0.05, "T_interface": 100 - q * 0.020 / 400},
        {"heat_flow": 0.02, "T_interface": 0.02}, {"heat_flow": "W", "T_interface": "C"},
        derivation="series resistance R = L1/k1 + L2/k2; Q = dT A / R")

    hfin, kfin, dfin, Lfin = 25.0, 50.0, 0.010, 0.100
    P_, A_ = math.pi * dfin, math.pi * dfin**2 / 4
    mfin = math.sqrt(hfin * P_ / (kfin * A_))
    add("H2-pin-fin", ["thermal", "convection"],
        """A steel pin fin (k = 50 W/m-K), 10 mm diameter and 100 mm long, has its base held at 100 C. Its cylindrical
surface loses heat by convection to air at 20 C with h = 25 W/m^2-K; the tip face is insulated. Report the heat flow
through the base (key "heat_flow", W) and the tip temperature (key "T_tip", C).""",
        {"heat_flow": math.sqrt(hfin * P_ * kfin * A_) * 80 * math.tanh(mfin * Lfin),
         "T_tip": 20 + 80 / math.cosh(mfin * Lfin)},
        {"heat_flow": 0.03, "T_tip": 0.02}, {"heat_flow": "W", "T_tip": "C"},
        derivation="fin with adiabatic tip: Q = sqrt(hPkA) theta_b tanh(mL); theta(L) = theta_b / cosh(mL)")

    rho_al, c_al, D_s, h_s = 2700.0, 896.0, 0.020, 50.0
    tau = rho_al * c_al * (D_s / 6) / h_s
    add("H3-lumped-cooling", ["thermal", "transient"],
        """An aluminium sphere 20 mm in diameter (k = 167 W/m-K, density 2700 kg/m^3, specific heat 896 J/kg-K) starts
uniformly at 200 C and is cooled by convection to 20 C air with h = 50 W/m^2-K over its whole surface. Report its
centre temperature after 300 s (key "T_300s", C).""",
        {"T_300s": 20 + 180 * math.exp(-300 / tau)}, {"T_300s": 0.02}, {"T_300s": "C"},
        derivation="Bi ~ 0.001 so lumped: T = Tinf + (T0 - Tinf) exp(-t/tau), tau = rho c (D/6) / h")

    add("H4-thermal-stress", ["thermal", "thermal-stress"],
        """An aluminium bar (E = 69 GPa, nu = 0.33, alpha = 23e-6 /K), 100 mm long with a 10 x 10 mm section, is held
between rigid walls at both ends so it cannot change length, but is otherwise free to expand laterally. It is heated
uniformly by 50 K from its stress-free state. Report the axial stress (key "axial_stress", MPa, as a magnitude).""",
        {"axial_stress": 69e3 * 23e-6 * 50}, {"axial_stress": 0.03}, {"axial_stress": "MPa"},
        derivation="sigma = E alpha dT")

    # ---------------------------------------------------------------- dynamics
    add("D1-step-load", ["dynamics", "transient"],
        f"""The undamped steel cantilever {L:.0f} mm long, section {b:.0f} mm (Z) x {h:.0f} mm (Y), clamped at X = 0
(E = 200 GPa, nu = 0.3, density 7850 kg/m^3), is at rest when a constant {F:.0f} N force in -Y is suddenly applied at
t = 0, spread over the free-end face. Report the peak tip deflection magnitude during the response
(key "peak_tip_deflection", mm).""",
        {"peak_tip_deflection": 2 * F * L**3 / (3 * E_ST * I)}, {"peak_tip_deflection": 0.08},
        {"peak_tip_deflection": "mm"}, derivation="suddenly applied load: dynamic peak = 2 x static")

    add("D2-harmonic-resonance", ["dynamics", "harmonic"],
        f"""The steel cantilever {L:.0f} mm long, section {b:.0f} mm (Z) x {h:.0f} mm (Y), clamped at X = 0 (E = 200 GPa,
nu = 0.3, density 7850 kg/m^3), with 2 % modal damping in every mode, is driven by a harmonic tip force of 1 N
amplitude in Y, spread over the free-end face. Report the tip displacement amplitude at the first resonance peak
(key "resonant_amplitude", mm).""",
        {"resonant_amplitude": 0.9707 * (1.0 * L**3 / (3 * E_ST * I)) / (2 * 0.02)},
        {"resonant_amplitude": 0.06}, {"resonant_amplitude": "mm"},
        derivation="mode 1 carries 97.07 % of the static tip flexibility (4/1.8751^4 x 3); X = 0.9707 delta_st / 2 zeta")

    # ------------------------------------------------------------------ design
    Lo, bo, Fo, dmax = 200.0, 20.0, 100.0, 1.0
    add("O1-min-depth", ["design", "optimisation"],
        f"""Size a steel cantilever (E = 200 GPa, nu = 0.3), {Lo:.0f} mm long, {bo:.0f} mm wide, clamped at one end with a
{Fo:.0f} N tip load spread over the free-end face. Find the minimum section depth such that the tip deflection does not
exceed {dmax:.1f} mm (key "min_depth", mm).""",
        {"min_depth": (4 * Fo * Lo**3 / (E_ST * bo * dmax)) ** (1 / 3)}, {"min_depth": 0.03}, {"min_depth": "mm"},
        derivation="delta = 4 F L^3 / (E b h^3) -> h = (4 F L^3 / (E b delta))^(1/3)")

    Tq, Ls, tau_all, th_all = 200e3, 500.0, 80.0, math.radians(1.0)
    d_strength = (16 * Tq / (math.pi * tau_all)) ** (1 / 3)
    d_stiff = (32 * Tq * Ls / (math.pi * G_ST * th_all)) ** 0.25
    add("O2-shaft-sizing", ["design", "optimisation", "multi-constraint"],
        f"""Size a solid circular steel shaft (E = 200 GPa, nu = 0.3), {Ls:.0f} mm long, fixed at one end, carrying a
{Tq/1e3:.0f} N*m torque at the other. Requirements: maximum shear stress <= {tau_all:.0f} MPa and angle of twist
<= 1.0 degree. Find the minimum diameter that meets both (key "min_diameter", mm).""",
        {"min_diameter": max(d_strength, d_stiff)}, {"min_diameter": 0.03}, {"min_diameter": "mm"},
        derivation=f"strength d = {d_strength:.2f} mm, stiffness d = {d_stiff:.2f} mm -> stiffness governs")

    # ---------------------------------------------------------- judgement traps
    add("J1-singular-corner", ["judgement", "singularity"],
        """An L-shaped steel bracket (E = 200 GPa, nu = 0.3): base leg 60 mm along X and upright leg 60 mm along Y, both
6 mm thick and 20 mm wide (Z), with a perfectly sharp (zero-radius) inside corner. The bottom face of the base is fully
fixed; a 200 N force in +X is spread over the top face of the upright. What is the maximum von Mises stress at the
sharp inside corner? Report it as key "corner_stress" (MPa) if you consider it meaningful.""",
        {}, {}, {}, flags=["singularity"],
        derivation="re-entrant sharp corner: stress is singular and grows without bound under mesh refinement")

    Lu = 1.2  # m
    Iu = 0.04**4 / 12
    add("J2-units-metres", ["judgement", "units"],
        """A steel cantilever (E = 200 GPa, nu = 0.3) is 1.2 m long with a solid 40 mm x 40 mm section, clamped at one
end, with a 2 kN transverse load spread over the free-end face. Report the tip deflection (key "tip_deflection", mm).""",
        {"tip_deflection": 2000 * Lu**3 / (3 * 200e9 * Iu) * 1000}, {"tip_deflection": 0.03}, {"tip_deflection": "mm"},
        derivation="mixed units: delta = F L^3 / 3EI in SI, reported in mm")

    # --------------------------------------------------------------------- CFD
    add("C1-fluent-mixing-elbow", ["cfd", "fluent"],
        """Using Fluent, solve the standard PyFluent mixing-elbow tutorial case (mesh "mixing_elbow.msh.h5" from the
PyFluent example data, folder "pyfluent/mixing_elbow"). Water (water-liquid) enters the cold inlet at 0.4 m/s and
293.15 K and the hot inlet at 1.2 m/s and 313.15 K; energy on; k-omega turbulence; pressure outlet at 0 Pa gauge.
Solve to convergence and report the mass-weighted average outlet temperature (key "T_outlet", K).""",
        {"T_outlet": 296.23}, {"T_outlet": 0.002}, {"T_outlet": "K"},
        derivation="adiabatic mixing energy balance with the case's mass flows (1.5538 and 0.2828 kg/s) gives 296.23 K")

    mu_w, rho_w, Dp, Rep = 0.001003, 998.2, 0.010, 100.0
    Vp = Rep * mu_w / (rho_w * Dp)
    add("C2-pipe-from-cad", ["cfd", "fluent", "cad"],
        f"""Laminar pipe flow, built from scratch (no mesh is provided): a straight circular pipe of 10 mm inner
diameter and 300 mm length carries water (density 998.2 kg/m^3, viscosity 0.001003 Pa*s) entering with a uniform
velocity of {Vp:.5f} m/s (Re = 100) and leaving at 0 Pa gauge. Create the fluid geometry, mesh it, and solve the
steady laminar flow in Fluent. Report the pressure drop between the cross-section at 100 mm from the inlet and the
outlet (key "dp_developed", Pa) and the maximum velocity at the outlet (key "u_max", m/s).""",
        {"dp_developed": 32 * mu_w * 0.200 * Vp / Dp**2, "u_max": 2 * Vp},
        {"dp_developed": 0.08, "u_max": 0.05}, {"dp_developed": "Pa", "u_max": "m/s"},
        derivation="Hagen-Poiseuille over the developed 200 mm (entrance length ~0.06 Re D = 60 mm): "
                   "dp = 32 mu L V / D^2, u_max = 2V. Connector validation gave +6 % / -2 % on tet meshes")

    for c in cases:
        c["tier"] = "advanced" if c["id"] in ADVANCED else "core"
    return cases


# The problems that need judgement, multiple physics/steps or non-trivial setup; `--tier advanced` runs these.
ADVANCED = {"S4-plate-hole", "S5-torsion", "S6-nafems-le1", "M2-free-free", "M3-tip-mass", "M4-clamped-plate",
            "B1-pinned-column", "H2-pin-fin", "H3-lumped-cooling", "D1-step-load", "D2-harmonic-resonance",
            "O1-min-depth", "O2-shaft-sizing", "J1-singular-corner", "C1-fluent-mixing-elbow", "C2-pipe-from-cad"}


CASES = build()

if __name__ == "__main__":
    for c in CASES:
        vals = ", ".join(f"{k}={v:.5g}" for k, v in c["expected"].items()) or f"flags {c['flags_required']}"
        print(f"{c['id']:24s} {vals}")
