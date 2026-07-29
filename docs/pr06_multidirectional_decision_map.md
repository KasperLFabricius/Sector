# PR-06 multidirectional crack and shear decision map

This map is the controlled implementation basis for F-009 and F-023. It was
prepared only from the local Design Basis library. The main Eurocode, each
applicable Danish National Annex, and owner/project authority sources were
classified separately. Sector does not infer a universal interaction rule from
two component checks.

The independent one-direction crack response and the independent `Vx`/`Vy`
shear results remain available in every case. A combined conclusion is withheld
unless the user opts into one method below and all of that method's current
domain, source, axis, calculation, and approval evidence passes the fail-closed
gate.

## Controlled sources

| ID | Classification | Exact local document and lifecycle |
|---|---|---|
| EC2-2004 | Normative Eurocode | `01_Standards/01_Denmark_Eurocodes/03_Concrete/00_Current/DS-EN 1992-1-1 (2004) - AC (2008).pdf`, EN 1992-1-1:2004 + AC:2008 |
| EC2-2004-A1 | Normative amendment, reviewed separately | `01_Standards/01_Denmark_Eurocodes/03_Concrete/00_Current/DS-EN 1992-1-1 (2004-A1-2015).pdf`; no replacement of the interaction provisions mapped below was identified |
| DKNA-2024 | Danish national choices | `01_Standards/01_Denmark_Eurocodes/03_Concrete/00_Current/DS-EN 1992-1-1 - DK NA (2024, rev 2024-02-01) [DA].pdf`, internally DS/EN 1992-1-1 DK NA:2021, revised 2024-01-09 |
| EC2-2023 | Normative Eurocode edition selected explicitly by the user | `01_Standards/01_Denmark_Eurocodes/03_Concrete/96_Published_Not_Implemented/DS-EN 1992-1-1 (2023).pdf`, EN 1992-1-1:2023. Its local catalog lifecycle is recorded; no Danish NA for this edition is inferred. |
| EC2-2 | Normative bridge Eurocode | `01_Standards/01_Denmark_Eurocodes/03_Concrete/00_Current/DS-EN 1992-2 (2005).pdf`, EN 1992-2:2005 |
| EC2-2-DKNA | Danish bridge national choices / owner publication | `01_Standards/01_Denmark_Eurocodes/03_Concrete/00_Current/DS-EN 1992-2 - DK NA (2015) [EN].pdf`, DS/EN 1992-2 DK NA:2015 |

PDF page numbers below are one-based file pages where given. Printed page
numbers are named separately where material.

## Offered crack-interaction methods

| Method ID and UI name | Exact source and physical meaning | Applicability domain | Required current inputs and evidence | Symmetry, sign, axes, and rotation | Calculation and conclusion | Fail-closed fallback |
|---|---|---|---|---|---|---|
| `crack-dk-na-2004-7.3.4` — **DS/EN 1992-1-1:2004 + DK NA inclined crack** | EC2-2004 7.3.4(4), Formula (7.15), PDF p.254 / printed p.126: spacing normal to an inclined crack from two orthogonal reinforcement spacings. DKNA-2024 7.3.4(4), Formula (7.101 NA), PDF p.41: the two directional mean strain-difference terms are added; tension stiffening is evaluated separately in each direction. When the elastic or optimum-plastic route is unavailable, DKNA Formula (7.102 NA) supplies the stated plane-stress angle equation. | Explicit DS/EN 1992-1-1:2004 + DK NA crack edition; member reinforced in two orthogonal directions; angle between principal tensile stress and the first reinforcement direction greater than 15 degrees and less than 90 degrees; plane-stress state at the assessed point; no unmodelled discontinuity claimed; one uniquely identified current Elastic case and existing canonical crack criterion/SLS combination. | Opt-in; distinct non-empty axis definitions; angle; positive finite `sr,x` and `sr,y`; finite non-negative directional strain-difference terms; individually confirmed domain checks; exact Elastic case ID; exact criterion ID and SLS combination; the current canonical criterion supplies the limit and remains bound to its immutable response evidence. The fixed standard source is recorded automatically. | With `theta` defined from axis x to principal tensile stress, `1/sr = cos(theta)/sr,x + sin(theta)/sr,y`. Swapping axes requires swapping component terms and replacing `theta` by `90 degrees - theta`. Non-negative crack terms make stress-sign reversal outside the routed tensile state inapplicable, not silently invariant. A rigid rotation is invariant only when both named axes and the principal direction rotate together. | `delta_epsilon = delta_epsilon_x + delta_epsilon_y`; `wk = sr * delta_epsilon`; `eta = wk / wlim`. A complete in-domain selected-standard calculation may return `PASS` or `FAIL` for this interaction criterion without changing the independent dominant-direction result. | `NOT ASSESSED / REVIEW`; retain the dominant-direction and every canonical criterion result. Never reuse response duration as an SLS-combination label and never substitute a generic max or power sum. |
| `crack-en-2023-g.5` — **EN 1992-1-1:2023 Annex G.5 membrane crack** | EC2-2023 9.2.3(7) and normative Annex G.5, Formulas (G.22)-(G.27), PDF pp.293-294 / printed pp.291-292: refined inclined-crack spacing and directional tension-stiffening strain terms for membrane elements. | Explicit EN 1992-1-1:2023 crack edition; membrane element without a discontinuity in the assessed region; reinforcement in two orthogonal directions; angle between principal compressive strain axis and x reinforcement strictly greater than 15 degrees and less than 75 degrees; one uniquely identified current Elastic case and canonical crack criterion/SLS combination. No Danish adoption or NA is inferred. | Opt-in; axes; angle; positive finite `sr,x` and `sr,y`; finite non-negative x/y strain-difference terms and `abs(epsilon_2)` term; each domain check; exact current Elastic case, criterion ID, and combination. Formula (G.24)/(G.25) source inputs may be externally calculated engineering inputs but remain visible and input-hash-bound. | Formula (G.22) uses `1/sr = sin(theta)/sr,x + cos(theta)/sr,y` with the source's angle definition. Axis swap requires component swap and `theta -> 90 degrees - theta`. A rigid rotation is invariant only with co-rotated axes and principal direction. The absolute transverse-strain term is sign invariant; applicability is not inferred from sign reversal. | `delta_epsilon = delta_epsilon_x + delta_epsilon_y + abs(epsilon_2)`; `wk = sr * delta_epsilon`; `eta = wk / wlim`. A complete result is an EN 1992-1-1:2023 interaction `PASS` or `FAIL`, never a Danish-NA verdict. | `NOT ASSESSED / REVIEW`; preserve all one-direction and criterion evidence. The 2004/DK formula is not substituted. |
| `crack-project-power-sum` — **Approved project crack power sum** | Project-defined methodology, not a Eurocode provision. The user-supplied source and approval define the physical acceptance surface `eta = (wk,x/wlim,x)^p + (wk,y/wlim,y)^p`. | Only the expressly approved project domain. Sector does not infer element type, exponent, equal limits, axis equivalence, symmetry, or standard adoption. | Opt-in; non-empty source and approval; positive finite exponent and per-axis limits; finite non-negative component widths; distinct axis definitions; explicit domain confirmation; exact current Elastic case, criterion ID, and SLS combination. | Axis-symmetric only when the approved inputs/limits are swapped with the axes. Rotationally invariant only for the special approved isotropic quadratic case (`p = 2` and equal directional limits); otherwise the method is directional. Width terms are non-negative. | Preserve both terms, the sum, parameters, and source. `eta <= 1` returns `APPROVED CUSTOM PASS`; otherwise `APPROVED CUSTOM FAIL`. It is never relabelled as an unqualified Eurocode result. | `NOT ASSESSED / REVIEW`; preserve components. No default exponent is authoritative merely because the UI pre-fills a value. |

## Offered shear-interaction methods

| Method ID and UI name | Exact source and physical meaning | Applicability domain | Required current inputs and evidence | Symmetry, sign, axes, and rotation | Calculation and conclusion | Fail-closed fallback |
|---|---|---|---|---|---|---|
| `shear-en-2023-8.2.1(5)` — **EN 1992-1-1:2023 planar resultant shear** | EC2-2023 8.2.1(5), Formulas (8.21)-(8.26), PDF p.117 / printed p.115: the out-of-plane shear-force components per unit width of a planar member are combined as a vector resultant, with a ratio- or angle-based effective depth. | Explicit EN 1992-1-1:2023 shear method; solid slab or shell/other planar member; both component actions refer to the same control point and orthogonal x/y axes; both are out-of-plane shear forces expressed on a compatible per-unit-width basis; current effective depths are valid; the resistance at the resultant direction/effective depth has an explicit current source and approval. No Danish-bridge applicability is inferred. | Opt-in; exact current `Vx`/`Vy` demands and their current widths/depths from the directional solver; distinct axis definitions; each domain check; chosen Formula (8.22)-(8.24) piecewise or Formula (8.25) rotated-depth route; positive finite resultant resistance per unit width; non-empty resistance source and approval. The resistance input is retained as an explicit engineering input and therefore qualifies the verdict. | Demand is sign-reversal invariant through squares. X/y swap is invariant when widths/depths and axis evidence are swapped. Formula (8.21) makes only the vector demand resultant rotationally invariant. The complete qualified check is recorded as directional because Sector has no evidence that the externally supplied resistance is isotropic; unequal depths and piecewise/directional resistance bases reinforce that limitation. | `vEd,x = abs(Vx)/bx`; `vEd,y = abs(Vy)/by`; `vEd = sqrt(vEd,x^2 + vEd,y^2)`. Effective depth and both resultant terms are recorded. `eta = vEd/vRd`. Because the resultant-direction resistance is externally evidenced rather than reconstructed by Sector, the conclusion is `QUALIFIED PASS` or `QUALIFIED FAIL`, never an unqualified Danish or full Eurocode resistance verdict. | `NOT ASSESSED / REVIEW`; retain independent component results. A pair of component passes is never used as the interaction result. |
| `shear-project-power-sum` — **Approved project shear power sum** | Project-defined methodology, not a Eurocode provision. The source and approval define `eta = (abs(Vx)/VRd,x)^p + (abs(Vy)/VRd,y)^p`. | Only the expressly approved project domain. Sector does not infer shell/member applicability, exponent, equal capacities, rotation invariance, or owner acceptance. | Opt-in; non-empty source and approval; positive finite exponent; distinct axes; domain confirmation; exact current component demands and the current governing component resistances from the solver. Missing, duplicate, invalid, or contradictory component evidence is rejected. | Axis-symmetric when components/resistances swap with axes. Sign-reversal invariant. Rigid-rotation invariant only for an approved isotropic quadratic case (`p = 2`, equal directional resistance, and vector components in a common basis); otherwise directional. | Record `eta_x`, `eta_y`, total utilisation, demands, resistances, exponent, source, and approval. `eta <= 1` returns `APPROVED CUSTOM PASS`; otherwise `APPROVED CUSTOM FAIL`. | `NOT ASSESSED / REVIEW`; preserve independent components. No default exponent becomes authority. |

## Sources reviewed but not offered as an interaction PASS

| Source | Decision |
|---|---|
| EC2-2004 / DKNA-2024 member shear clauses | No universal `Vx`/`Vy` member interaction was identified. Sector therefore keeps independent component results and does not infer a power sum or vector resultant for this edition. |
| EC2-2 informative Annex LL, especially Formulas (LL.121)-(LL.123) | Annex LL contains a shell-model resultant and projected reinforcement rule, but EC2-2-DKNA p.5 explicitly says Annex LL is not applicable. It is not offered under the Danish bridge method. |
| EC2-2 informative Annex QQ | The annex concerns shear-crack control and records large model uncertainty; EC2-2-DKNA p.5 explicitly says Annex QQ is not applicable. It is not a substitute for the crack methods above. |
| EC2-2 informative Annex MM | EC2-2-DKNA p.5 explicitly says Annex MM is not applicable. |
| Owner/project authority documents in the local library | No mapped owner source was found that supplies a universal replacement interaction. A project-defined method is therefore available only with explicit source and approval and only as a qualified custom verdict. |

## Evidence and invalidation contract

- Crack and shear method selections, source/approval fields, domain checks,
  editions, axis definitions, direction/sign-bearing inputs, depth route, and
  on/off switches are separate and enter the calculation signature.
- Every interaction result records the selected method and edition, formula,
  parameters, source/approval, domain checks, axes, component
  demands/resistances or crack terms, interaction terms, utilisation, and
  conclusion.
- Crack interaction identifies one current Elastic case and one existing
  canonical criterion by exact identity and SLS combination. Duration is retained
  as response evidence but never routes the interaction.
- Missing, duplicate, contradictory, malformed, Boolean, non-finite, stale, or
  self-consistent-but-not-current evidence rejects the combined conclusion.
  Positive finite custom engineering values calculate and remain visible.
  When an approved power-sum value exceeds finite floating-point range, the
  sealed evidence records a conservative finite lower bound and a saturation
  marker; the conclusion is `FAIL`, not an input rejection or crash.
- Current-schema omissions fail closed. Legacy projects migrate with both
  interactions explicitly off and no synthesized source, approval, or authority.
- Live results, durable session results, project save/load/resave,
  autosave/download, report, and manual use one publication-safe interaction
  record and one current-input fingerprint. Sealed crack and shear evidence is
  also re-assessed against the current canonical crack result and directional
  shear results before publication; deleting every aggregate representation
  produces a durable rejection. Rejection remains latched until a new
  calculation on valid current inputs.

## Independent oracle obligations

The PR-06 oracle is independent of production rule helpers and freezes:

- both uniaxial limits, zero component, balanced biaxial action, and points just
  below, exactly on, and just above each interaction boundary;
- x/y swap, physical sign reversal, rigid rotation for an isotropic quadratic
  method, and directional/anisotropic non-invariance;
- malformed, Boolean, non-finite, and positive finite custom parameters;
- unsupported domain, method/edition switch, stale/missing/duplicate evidence,
  calculation disabled/enabled, and current-input correlation;
- save-load-resave plus session, autosave, download, and publication bypass
  probes;
- explicit false-PASS cases proving that two component `PASS` results cannot
  become an unqualified combined `PASS` without a current applicable method;
- crack-history independence and canonical acceptance-combination routing; and
  shear component retention when the aggregate is `NOT ASSESSED`.
