# PI-019 calculation-trace coverage

Document status: controlled implementation map

Product version: Sector 0.91

Change scope: Sector v0.92 PR-08, Product Identity PI-019 only

Implementation branch: `codex/pr08-standards-calculation-trace`

Governing contract: `docs/product_identity.md` and Product Identity row PI-019 in
`Sector_QA_Review_2026-07-29.xlsx`

## Control rules

1. A calculation marked **covered** has one solver-owned structured trace. The
   Streamlit view, generated calculation report and issued manual consume that
   trace without re-evaluating an engineering formula.
2. Every trace step has a stable ID and dependency IDs; a quantity role; symbol;
   unit; source citation where the value or equation comes from a standard;
   symbolic equation; numerical substitution; evaluated value; and any warning
   or assumption needed to understand the step.
3. A user-entered value remains a user input. A selected standard default remains
   a method value. A derived term remains a computed intermediate. A reported
   governing quantity is a final result.
4. Project-defined numerical procedures and custom values are labelled as such.
   They do not receive invented standards citations. A positive finite custom
   value is retained as entered; divergence from a preset can warn but does not
   clamp, reject, approve or certify it.
5. An enabled calculation with no valid trace is not silently published as
   traced. Before sealing, a family-by-family audit matches every completed
   case, check, pair, spectrum record and bridge row to its trace; an unrelated
   material or result trace cannot hide an omitted family. Trace validation
   also fails closed for missing or duplicate dependencies, stale input
   identity, invalid units, non-finite or Boolean values, an altered content
   seal, or a standards citation attached to a user-defined method.
6. Traceability is calculation evidence, not a code-completeness, authority,
   project-basis, cover, combination-completeness or global-compliance verdict.
7. Every section-solver trace carries the exact ordered outer and hole vertices,
   every bar and tendon coordinate, and every point-element area used by that
   solver state. User-visible labels that enter trace namespaces retain a
   readable slug plus an injective token of their exact UTF-8 value.

## Publication surfaces

| Surface ID | Publication surface | Current implementation | PI-019 control |
|---|---|---|---|
| PUB-01 | Streamlit result views | `app/sector_app.py` | Render validated trace steps for the selected current case; do not derive engineering values in the view. |
| PUB-02 | Calculation / QA report | `app/sector_report.py` | Render the same validated trace bundle, ordered by calculation and dependency. |
| PUB-03 | In-app manual | `app/manual.py` | Render supported-method reference traces from the same model and solver-side builders. |
| PUB-04 | Issued PDF manual | `app/manual.py` | Render the identical manual trace blocks used by PUB-03. |
| PUB-05 | Project save/load | `app/project_io.py` | Current schema only. Calculation traces are current-result evidence and remain correlated to the exact input signature; stale or corrupt trace publication is rejected. |

## Retained numerical-kernel coverage

Status meanings:

- **planned** - retained and published today; PR-08 implementation is required.
- **covered** - implemented, exercised by an independent numerical oracle and
  rendered from the shared trace.
- **not standards-based** - retained numerical output whose method is explicitly
  project-defined; it still receives a labelled trace when it is a dependency of
  a covered standards calculation.
- **not exposed** - not published as a completed calculation. It must not be
  represented as covered.

| Trace family | Retained kernel / method | Solver owner | Governing local source route | Report / UI surface | Initial status |
|---|---|---|---|---|---|
| CT-001 | Concrete, mild-steel and tendon design properties / constitutive selections. Reinforcement provenance follows the actual selected material-catalogue preset independently of the concrete preset; custom/imported laws receive no standards citation. | `sector/codes.py`, `sector/materials.py`, `sector/material_presets.py` | DS/EN 1992-1-1:2004+A1:2014/AC, clauses 3.1.6-3.1.7, 3.2.7 and 3.3.6; DS/EN 1992-1-1:2023, 5.1.6, 5.2.4, 5.3.3 and 8.1.1-8.1.2 | Theory/material tables and all dependent calculations | planned |
| CT-002 | Plastic section capacity and M-M envelope using selected constitutive laws. The exact ordered outer and hole vertices and every bar/tendon coordinate and area are solver-input dependencies. Every solver-aligned bar and tendon law records its actual strengths, factors, modulus, strain limits, compression state and tendon prestrain as transitive capacity dependencies; the retained governing state carries its actual curvature, tension-positive axial resultant, compression resultant, lever arm and convergence state; mixed standard/project selections are labelled explicitly. | `sector/plastic.py` | DS/EN 1992-1-1:2004+A1:2014/AC, 3.1.7, 3.2.7, 3.3.6 and 6.1; DS/EN 1992-1-1:2023, 5.1.6, 5.2.4, 5.3.3 and 8.1.2 | Plastic results and worked calculation | planned |
| CT-003 | Radial M-M demand / resistance utilisation | `sector/combined.py` | Sector geometric intersection of the CT-002 capacity envelope; no normative equation assigned | Plastic results and summary | not standards-based |
| CT-004 | N-M interaction boundary using selected constitutive laws. Every traced boundary state repeats the calculation-local exact section geometry plus the concrete, element-aligned bar and tendon dependency chain used by the interaction solver. | `sector/plastic.py` | Same source route as CT-002 | N-M interaction view and report | planned |
| CT-005 | Cracked / uncracked elastic section equilibrium, transformed properties and combined creep superposition. Each calculation records the exact section geometry, the element-specific modulus, reference-modulus multiplier, short/long modular ratios and tendon prestrain / locked prestress `Ep eps_p0` used by the solver. A legitimate infinite first-cracking factor is retained in solver output and traced through finite tensile-reachability leaves instead of being omitted. | `sector/elastic.py`, `sector/serviceability.py` | Section equilibrium is a Sector numerical procedure; selected material values remain input/project evidence without invented standards citations | Elastic results and report | not standards-based |
| CT-006 | 2005 ordinary crack width | `sector/serviceability.py` | DS/EN 1992-1-1:2004+A1:2014/AC, 7.3.2 and 7.3.4, Formulae (7.8), (7.9), (7.11), (7.14) | Elastic crack results and report | planned |
| CT-007 | 2005 + DK NA:2024 fine and coarse crack systems | `sector/serviceability.py` | CT-006 base standard reviewed separately from DK NA:2024, 7.3.2(3), 7.3.4(1), 7.3.4(3), Figure 7.100 NA | Elastic crack results and report | planned |
| CT-008 | 2023 refined bending and direct-tension crack width | `sector/serviceability.py` | DS/EN 1992-1-1:2023, 9.2.2-9.2.3, Formulae (9.8)-(9.20) and Figure 9.3 | Elastic crack results and report | planned |
| CT-009 | 2005-family shear without links | `sector/shear.py`, `sector/capacity.py` | DS/EN 1992-1-1:2004+A1:2014/AC, 6.2.2, Formulae (6.2a)-(6.3); DK NA:2024 6.2.2(1) reviewed separately | Shear view and report | planned |
| CT-010 | 2023 strain-based shear without links | `sector/shear.py`, `sector/capacity.py` | DS/EN 1992-1-1:2023, 8.2.1-8.2.2, Formulae (8.18), (8.20), (8.27), (8.29)-(8.31) | Shear view and report | planned |
| CT-011 | 2005-family shear with links and compression-field limit | `sector/shear.py`, `sector/capacity.py` | DS/EN 1992-1-1:2004+A1:2014/AC, 6.2.3, Formulae (6.8)-(6.9); DK NA:2024 5.6.1(3)P and 6.2.3(2)-(3) reviewed separately | Shear view and report | planned |
| CT-012 | 2023 shear with links and compression-field limit | `sector/shear.py`, `sector/capacity.py` | DS/EN 1992-1-1:2023, 8.2.3, Formulae (8.42), (8.44), (8.50)-(8.52) | Shear view and report | planned |
| CT-013 | Thin-walled tube torsion; compound-section distribution | `sector/torsion.py`, `sector/capacity.py` | DS/EN 1992-1-1:2004+A1:2014/AC, 6.3.1-6.3.2, Formulae (6.26)-(6.31); DK NA:2024 5.6.1(3)P and 6.3.2(6) reviewed separately | Torsion view and report | planned |
| CT-014 | Shared transverse reinforcement and V-T crushing interaction | `sector/combined.py`, `sector/capacity.py` | DS/EN 1992-1-1:2004+A1:2014/AC, 6.3.2(4), Formula (6.29); DS/EN 1992-1-1:2023, 8.2.3 where selected | Combined view and report | planned |
| CT-015 | Longitudinal chord addition from shear / torsion | `sector/combined.py`, `sector/capacity.py` | 2005 family: 6.2.3(7) and 6.3.2; 2023: 8.2.3(8), Formulae (8.50)-(8.52) | Combined view and report | planned |
| CT-016 | DK NA M-V-T interaction sum | `sector/combined.py`, `sector/capacity.py` | DK NA:2024, 6.3.2(6), reviewed separately from base EN 1992-1-1 | Combined view and report | planned |
| CT-017 | Minimum longitudinal reinforcement, 2005 / DK NA. A selected tension zone with no usable reinforcement publishes the cited symbolic formula, actual available leaves and a finite zero availability state; it does not invent `fyk`, `As,min` or utilisation. | `sector/detailing.py` | DS/EN 1992-1-1:2004+A1:2014/AC, 9.2.1.1(1), Formula (9.1N); DK NA:2024 9.2.1.1(1) separately | Detailing view and report | planned |
| CT-018 | Minimum longitudinal reinforcement, 2023. Zero nominal resistance and an infeasible axial envelope publish finite resistance-minus-demand evidence while the solver result retains its failure state. | `sector/detailing.py` | DS/EN 1992-1-1:2023, 12.2(2), Formulae (12.1)-(12.2) | Detailing view and report | planned |
| CT-019 | Minimum transverse ratio, required-link state and link spacing. Absent/effectively-zero provision publishes the actual finite provision-minus-requirement margin while retaining the solver-owned infinite utilisation. | `sector/detailing.py` | 2005 family: 9.2.2(5), Formulae (9.4)-(9.5), DK NA separately; 2023: 12.2(4), Formula (12.4) and Table 12.1; the exact selected requirement clause is carried per check | Detailing view and report | planned |
| CT-020 | Pairwise clear spacing | `sector/detailing.py` | 2005 family: 8.2(2); 2023: 11.2(2) | Detailing view and report | planned |
| CT-021 | Reinforcement S-N fatigue life and Miner accumulation | `sector/fatigue.py`, `app/fatigue_analysis.py` | 2005: 6.8.2, 6.8.4, Tables 6.3N/6.4N; 2023: Annex E.5, Tables E.1/E.2 | Fatigue view and report | planned |
| CT-022 | Concrete fatigue, 2005 equivalent-stress method | `sector/fatigue.py`, `app/fatigue_analysis.py` | DS/EN 1992-1-1:2004+A1:2014/AC, 6.8.7, Formulae (6.72) and (6.76) | Fatigue view and report | planned |
| CT-023 | Concrete fatigue, corrected bridge Miner method | `sector/fatigue.py`, `app/fatigue_analysis.py` | DS/EN 1992-1-1:2004+A1:2014/AC 6.8.7 Formula (6.76); DS/EN 1992-2:2005, 6.8.7(101), Formulae (6.105)-(6.109), with AC:2008 corrected Formula (6.106) reviewed separately | Fatigue view and report | planned |
| CT-024 | Concrete fatigue, 2023 equivalent and Miner methods | `sector/fatigue.py`, `app/fatigue_analysis.py` | DS/EN 1992-1-1:2023, 10.5 Formula (10.5), E.4.3 Formula (E.2), E.5.1 Formula (E.3) and E.5.3 Formulae (E.7)-(E.8) | Fatigue view and report | planned |
| CT-025 | Bridge brittle-failure Method B minimum steel | `sector/bridge.py` | DS/EN 1992-2:2005, 6.1(109)-(110), Formula (6.101a) | Bridge view and report | planned |
| CT-026 | Bridge box-wall shear / torsion interaction | `sector/bridge.py` | DS/EN 1992-2:2005, 6.3.2(101)-(104), Formulae (6.29)-(6.30), with AC:2008 reviewed separately | Bridge view and report | planned |
| CT-027 | Bridge minimum crack reinforcement | `sector/bridge.py` | DS/EN 1992-2:2005, 7.3.2(102)-(105), Formula (7.1) | Bridge view and report | planned |

## Local Design Basis evidence

Only the local Design Basis library is used for PR-08 clause and equation
verification. No online standards source is used.

| Authority layer | Local controlled candidate | PI-019 use |
|---|---|---|
| Main standard | `01_Standards/01_Denmark_Eurocodes/03_Concrete/00_Current/DS-EN 1992-1-1 (2004) - AC (2008).pdf` | Base 2004 text and integrated AC route. |
| Amendment | `.../DS-EN 1992-1-1 (2004-A1-2015).pdf` | A1 applicability for the retained 2005-family methods. |
| Corrigendum | `.../DS-EN 1992-1-1 - AC (2010).pdf` | Separate corrigendum review where a cited clause is affected. |
| Danish National Annex | `.../DS-EN 1992-1-1 - DK NA (2024, rev 2024-02-01) [DA].pdf` | Danish parameter and method modifications, reviewed separately from the base standard. |
| Published selectable method | `.../96_Published_Not_Implemented/DS-EN 1992-1-1 (2023).pdf` | Clause verification for the explicitly selectable 2023 calculation method; its library location is not represented as a Danish applicability decision. |
| Bridge standard | `.../00_Current/DS-EN 1992-2 (2005).pdf` | Retained bridge-direct and concrete-fatigue kernels. |
| Bridge corrigendum | `.../00_Current/DS-EN 1992-2 - AC (2008).pdf` | Corrected Formula (6.106) and affected bridge clauses, reviewed separately. |
| Bridge Danish NA | `.../00_Current/DS-EN 1992-2 - DK NA (2015) [DA].pdf` and `[EN].pdf` | Checked separately when a national bridge parameter is claimed; no authority-routing conclusion is produced. |

## Exclusions preserved

PR-08 does not restore or introduce SLS stress/crack acceptance limits,
required-combination acceptance, generic multidirectional aggregation, a Danish
cover calculator, authority routing, legacy schema migration, compliance
apparatus or a global verdict. The trace reports numerical calculation evidence
and genuine demand-versus-resistance equation outcomes only.

## Closure record

The status column is updated from **planned** to **covered** only when all of the
following exist at one immutable head:

1. solver-side trace construction and strict schema validation;
2. independent dependency-by-dependency numerical oracle;
3. Streamlit/report/manual reuse test;
4. rendered report and manual page inspection;
5. exact-head full-suite, test-report and package-content gates; and
6. independent exact-SHA adversarial acceptance by the supervising reviewer.
