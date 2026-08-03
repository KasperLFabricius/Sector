# PR-09B acceptance: complete numerical-method contract and example

Exact base: `7512c3ed01e41100cee59893ce9beab381bec890`.

Finding F-036 is the sole scope. The contract is derived from merged solver and
project code, retained output payloads, accepted tests and the QA finding. Closed
PR #284 and PR #285 heads are negative evidence only and are absent from ancestry.

## Complete method inventory

| Method | Published normal and exceptional branches |
|---|---|
| Plastic axial solve | Initial and expanded bracket, 80-expansion cap, endpoint reachability including equality, 100-step bisection, depth-width stop, final-midpoint evaluation, residual tolerance, and the fact that bisection-cap exhaustion is not an independent failure flag. |
| Cracked Elastic | Uncracked initial solve, zero fallback for a singular initial matrix, compression-zone reclipping, scaled infinity-norm test, 100-step cap, singular tangent exit and not-converged result. |
| Applied ray | Zero-demand branch, parallel-edge and edge-parameter bands, nearest forward chord crossing, no-crossing infinity, nearest chord endpoint as governing member, and first-endpoint tie break. |
| Concrete fatigue search | Empty-bound completion, dominated-box removal, finite global-gap certificate, depth/box limit exits, and the explicit positive-infinite sampled-damage exception (`converged=True`, infinite recorded gaps). |
| Report precision | Calculations and verdicts use unrounded retained values; fixed-decimal and significant-digit formatting are presentation only. |

## Reproducible example

- Publish a current-schema Sector project and a compact checking pack from the
  manual dialog.
- Retain example identity only in ordinary project metadata; use the genuine
  current `source_revision` in provenance.
- Bind downloads by the exact saved-input SHA-256.
- Use a centred 300 x 600 mm C40/50 beam with three 25 mm bottom bars and two
  16 mm top bars, all assigned to mild-steel material ID `M1`.
- Plastic case: `(N, Mx, My) = (0, 180, 30)` with a 15-degree full-turn sweep.
- Elastic case: long `(0, 60, 10)` plus short `(0, 30, 5)`, creep 3.0 and DK NA
  crack-width method.
- Independently reconstruct key unrounded plastic, elastic and crack results from
  parsed original inputs. Load and calculate the actual download through the
  Streamlit application in the focused CI test.

## Exclusions

No solver, formula, material law, project schema, report renderer, version,
fatigue spectrum, shear, torsion, M-V-T, detailing or independent bridge example
change. PR-10 layout/notation, PR-11 publication identity/preflight, PR-12 UI,
PR-13 CI, PR-14 packaging/signing and v0.93 work remain excluded.
