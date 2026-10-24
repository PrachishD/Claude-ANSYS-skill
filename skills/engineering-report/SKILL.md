---
name: engineering-report
description: Write an engineering report (HTML + Word) for a finished Ansys study with the report_create tool - title block, model, loads, results with margins, verification table, convergence, images, assumptions and sign-off. Use when the user asks for a report, write-up, calc sheet, documentation or something to share with a team or reviewer, or at the end of a study they will act on.
---

# Engineering report

Write the report only **after** the study is solved and verified. The report presents work already done; it never replaces it. Make one `report_create` call with everything filled in.

## Fill the spec honestly

- **verdict:**
  - `PASS` only if every requirement is met *and* every verification check passed.
  - `FAIL` if a requirement is violated.
  - `REVIEW` if a result is uncertain (an unconverged quantity, a guessed input, a singularity near the critical point).
- **summary:** 3–6 sentences covering what was analysed, the governing numbers and the verdict. Lead with the answer.
- **results:**
  - Give each quantity a `limit` and a `margin` where a requirement exists. Express margins as SF = allowable/actual, or as the % distance from a band.
  - Use `status` on the governing rows.
- **verification:** list the checks you **actually ran**, with expected vs actual, for example:
  - equilibrium (reactions vs loads)
  - hand calculation
  - energy or mass balance
  - singularity handling
  - inputs re-read

  Never invent a check. If you skipped one, say so in `limitations`.
- **convergence:** one row per mesh, with the governing quantity and the % change.
- **images:** the PNG paths the solver tools returned (stress contour, mode shapes, temperature). Two or three is enough.
- **assumptions / limitations:** every modelling choice that could move the answer, for example:
  - boundary conditions
  - lumped masses and their inertia
  - linear vs nonlinear
  - static treatment of dynamic loads
  - guessed material data
- **recommendations:** concrete next steps, like a design change, a test, or a refined model.
- **files:** model and results paths, so someone can reproduce the study.

Default `sign_off: true`: these results need a human engineer's check before use.

After the call, give the user both file paths. If the session can publish artifacts, offer to share the HTML report as a page.
