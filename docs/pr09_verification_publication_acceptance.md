# PR-09 verification publication acceptance matrix

## Frozen base and purpose

- Base commit: `28f0b758bc83ce5ceeb99afb8efe45d906a46049`.
- Application version: `0.91`; project schema: `23`.
- Finding family: F-017, F-033, F-035 and F-036 only.
- Purpose: make the accepted mechanics, numerical controls, failure states and one
  complete worked project independently reproducible without changing a solver
  equation, input identity, result identity or verdict.

The QA workbook is an index to these defects, not evidence of the current
implementation. The contract below was reconstructed from merged main, the live
input/result payloads, accepted tests, `docs/geometry_topology.md`, and the local
Design Basis copy of DS/EN 1992-1-1 clause 3.2.7.

## Authoritative sources

1. Current merged geometry, material, plastic, elastic, fatigue and publication
   code at the frozen base.
2. Existing accepted mechanics and adversarial tests.
3. `docs/geometry_topology.md` for the already-implemented proactive geometry
   rejection boundary.
4. Local `DS-EN 1992-1-1 (2004) - AC (2008).pdf`, clause 3.2.7, for the two
   permitted reinforcing-steel design-diagram assumptions.

No internet source or rejected PR head is an implementation source.

## F-017: geometry-validation claim

The manual must say that geometry is rejected before calculation when any of the
following current conditions applies:

- a ring is non-numeric, non-finite, too short or below the scale-aware area
  tolerance;
- a ring self-crosses, self-touches, overlaps or backtracks;
- vertices or non-adjacent boundaries are coincident within the resolved linear
  tolerance;
- a hole touches/crosses the outer boundary, lies outside it, touches/crosses
  another hole or is nested in another hole;
- a void disconnects the remaining concrete; or
- a bar or tendon is outside the concrete or inside a void.

Clockwise/counter-clockwise winding, intentional forward collinear points and one
exact terminal closure marker remain accepted. The manual must distinguish these
input validation failures from a solver that receives valid geometry but returns
nonconvergence or an invalid result.

## F-033: tendon-coordinate and sign convention

For neutral-axis angle `phi_NA`, the solver projection is

`s = x cos(phi_NA) + y sin(phi_NA)`, with `s_na = s_max - c`.

The internal section strain is compression-positive,
`epsilon_sec(s) = kappa (s - s_na)`. Therefore smaller `s` is the tension side;
published strains negate the internal sign. The tendon coordinate in the rupture
term is `s_p,j`, and its most tensile shorthand is `s_p,min`. The undefined
`s_cab,min` symbol is forbidden.

The manual equation must retain element-specific material limits:

- concrete: `epsilon_cu2 / c`;
- every tensile mild bar: `epsilon_ut,i / (s_na - s_i)`;
- every compression-active mild bar on the compression side:
  `epsilon_ut,i / (s_i - s_na)`;
- every tendon on the tension side with positive remaining strain margin:
  `(epsilon_pud,j - epsilon_p,IS,j) / (s_na - s_p,j)`.

This is documentation of the existing per-element loop, not a formula change.

## F-035: mild-steel preset identity

Stored preset strings and all numerical material fields remain unchanged.
Presentation must distinguish:

- the generic Curve 1, Curve 2 and Curve 3 choices as user-defined law shapes;
- custom/imported material as user-defined/imported and uncited; and
- edition-named choices as Eurocode design presets implemented through the
  general Curve-3 law.

The edition presets use the horizontal design branch permitted by DS/EN
1992-1-1 3.2.7, with `gamma_E = 1` and yield strain `f_yd / E_s`. The generic
Curve-2 law is a user-defined legacy shape whose elastic slope is factored with
`gamma_y`, giving yield strain `f_yk / E_s`. Numerical-law equality must never
promote a user-defined material to an edition preset or citation.

The UI and report use the same display helper. Project JSON, signatures, trace
identities and material construction continue to use the original stored value.
The manual beam example must use the edition preset law it describes.

## F-036: numerical-method disclosure

The manual must publish the following retained controls and failure meanings.

### Plastic capacity and envelope

- 80 concrete integration bands by default.
- Compression-depth bracket starts at `1e-9 c_full`; the compression endpoint may
  grow by at most 80 doublings.
- At most 100 bisection iterations; depth stop `1e-12 c_full`.
- Convergence requires both endpoint reachability and axial residual
  `|N_int - N_Ed| <= 1e-6 max(1, |N_Ed|)`.
- The envelope uses the entered angle range and a normalised increment that lands
  exactly on both endpoints.
- Conditional chord capacity searches the full circle with 36 initial intervals,
  refines crossings/extrema to 0.005 degrees, and caps golden-section refinement
  at 60 iterations. A failed internal solve returns an inexact fallback state;
  an exhausted correct-face branch may return a genuine exact zero.

### Elastic and cracking

- Cracked equilibrium is Newton iteration from the uncracked solution, at most
  100 iterations.
- Convergence uses the infinity norm of the three resultant residuals and the
  bound `1e-9 max(1, ||target||_inf)`.
- A singular Jacobian or exhausted iteration cap is nonconverged. It is not a
  resistance, pass/fail verdict or large finite substitute.
- Stage-I uncracked equilibrium is one linear solve; a singular matrix is an
  explicit nonconverged result.

### Concrete fatigue fibre search

- Priority branch-and-bound begins with a 4 by 4 grid, with maximum depth 26 and
  maximum 200,000 evaluated boxes.
- The retained convergence certificate is
  `upper - best <= 1e-8 + 1e-3 max(|best|, 1e-12)`.
- Repeated equal samples alone never certify convergence. Exhausted limits with a
  remaining bound gap are nonconverged.

### Report precision and failure publication

- Ordinary values use the field's declared fixed decimal precision.
- Small nonzero engineering evidence uses six significant digits so it cannot
  round to a displayed zero.
- `None` displays as unavailable; positive/negative infinity remains explicit.
- Unsupported, invalid and nonconverged branches must not fabricate resistance,
  utilisation or an engineering verdict.

## Complete worked example and frozen oracle

PR-09 supplies one current-schema project download and one compact hand-calculation
pack from the Project & report panel. The example activates every main calculation
chapter represented by current main: plastic, elastic/crack, grouped fatigue,
minimum reinforcement, transverse detailing, clear spacing, shear, torsion,
combined interaction, independent bridge calculations and structured traces.

The project is loaded through the same current-schema parser as a user file and is
calculated through the same app orchestration. A frozen literal oracle, independent
of the returned result object, pins unrounded representative outputs, calculation
states, method/formula identifiers, section/material identity and result-family
presence. Tests also reconstruct representative hand equations from original
inputs. No candidate-selected governing state or rounded report text is trusted.

## Explicit exclusions

- No solver, resistance, fatigue, cracking, geometry or material-law formula
  change.
- No project-schema, trace-schema, version, Product Identity or standards-scope
  change.
- No report pagination, equation numbering or shared publication-style work owned
  by PR-10/PR-11.
- No navigation, rerun or telemetry work owned by PR-12.
- No typing/coverage boundary work owned by PR-13.
- No executable metadata, signing, cold-start or reproducibility work owned by
  PR-14.
- No v0.93 candidate, removed PR-07 functionality, legacy schema or rejected-head
  code.

## Focused acceptance

1. Stored preset values round-trip unchanged while UI/report labels are explicit.
2. The manual's app and PDF renderers share the corrected source blocks.
3. Every numerical constant above is pinned against the merged implementation.
4. The worked project parses, loads, calculates and publishes every declared
   result family without application exceptions.
5. Frozen unrounded oracle values and independent formula checks close.
6. ASCII, version, compile, static-analysis, base and rejected-ancestry guards are
   green.
