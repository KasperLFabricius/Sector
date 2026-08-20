# PR-A03 v0.95 torsion-link input and publication semantics acceptance

## Exact boundary

- Exact base: `2a2f2a272716466adc07cd12c71f9b6f241d4e49`.
- Base tree: `d9890f401aec94b548ce7bbbd699208908b94879`.
- Product version remains `0.94`; project schema remains `25`.
- Owner outcome: `OA095-002` - require current closed torsion links for full
  torsion resistance and make shear-link versus torsion-link semantics explicit
  across input, Results and publication.
- Dependency: PR-A02 is merged and supplies the dormant
  `select_full_torsion_resistance` authority contract.
- Change family: atomic activation of that authority through the existing
  persisted link input, retained torsion result and its application/report/manual
  publication surfaces.

This PR does not create a calculation certificate, project approval or global
compliance verdict. It changes one component assessment so that Sector cannot
publish a full torsion resistance without the reinforcement that the selected
model requires.

## Engineering authority

The existing persisted `shear_links` Boolean is the single current physical
authority for the shared transverse reinforcement:

- for shear, the selected number of effective vertical legs resists the shear
  action;
- for torsion, one leg of the same closed, anchored loop resists the thin-walled
  shear flow around the perimeter; and
- positive stored diameter, spacing or yield values never imply that such a
  loop is present.

`TRd,s` is the transverse-reinforcement resistance. `TRd,max` is the
concrete-strut maximum used by Formulae 6.29/6.30, and `TRd,c` is cracking
transparency. Neither concrete quantity becomes a standalone full torsion
resistance when current closed links are absent. The application may retain the
tube geometry, concrete quantities and calculated reinforcement demand for
transparency, but it must not publish `TRd`, utilisation, a governing resistance
or PASS/FAIL from them.

## Input and persistence contract

1. The existing `shear_links` project key is relabelled as the shared link /
   closed-torsion-stirrup authority. No second authority is introduced.
2. The widget is available whenever shear or torsion is enabled. It remains a
   stable keyed Boolean so an existing project and Streamlit session keep the
   same stored value.
3. The strut-angle band may remain available for an informational torsion
   concrete cap. Bar diameter, spacing, link yield and directional shear-leg
   inputs are active only when the shared link authority is true; shear legs do
   not multiply the one-leg torsion reinforcement.
4. `torsion_nu_v` cannot receive the favourable closed-detailing credit unless
   current closed links are true. A stale checked value is retained as user
   input but is explicitly not applied while the authority is false.
5. A current serialized `shear_links` value must be an exact JSON Boolean.
   Missing legacy/current-schema evidence is normalized to `false`, which clears
   any previously true session value on load. Text, numeric and null values are
   rejected rather than truthiness-coerced.
6. The existing project schema stays at 25. Project hashes and calculation
   signatures continue to include `shear_links`, so changing the authority makes
   a retained calculation stale. The capacity-result contract token is advanced,
   so a live pre-A03 Streamlit session must recalculate even when its input values
   have not changed.

## Retained calculation contract

Each torsion result separates tube formation from full-resistance assessment:

- `tube_valid`: whether the thin-walled tube or validated sub-tube partition is
  geometrically usable;
- `closed_links_present`: the exact current shared-link authority;
- `full_resistance_assessed`: the PR-A02 selector outcome;
- `assessment_reason`: the selector's stable reason when full resistance is not
  assessed;
- `valid`: true only when the tube is valid and full resistance is assessed;
  and
- `resistance_selection`: the complete PR-A02 selector result.

When the tube is valid but current closed links are absent:

- current torsion `Asw/s` and `TRd,s` are zero regardless of stale positive
  geometry retained in the input state;
- `TRd,max`, `TRd,c`, tube properties, the displayed cap angle and the calculated
  longitudinal-reinforcement demand may be retained as clearly labelled
  transparency;
- `TRd`, utilisation and governing resistance are `None`;
- no combined shear-torsion interaction, shared-stirrup result or longitudinal
  interaction verdict may consume the unassessed torsion component; and
- the stable reason is `closed_links_not_present`.

With current closed links true but non-positive current one-leg reinforcement,
the same fields are withheld with
`closed_link_reinforcement_not_positive`. With positive current reinforcement,
the existing equations, angle selection, methods, units and precision are
unchanged and full resistance is selected as `min(TRd,s, TRd,max)`. An honest
zero selected capacity remains an assessed failure-capable state rather than
missing evidence.

For a subdivided section the rule applies to every sub-tube. Without current
closed links, Sector may retain each validated tube, torque share, `TRd,max` and
`TRd,c`, but it publishes no sum of full capacities, governing sub-tube,
utilisation or full-resistance verdict.

## Status and publication contract

1. **Results Overview.** A geometrically valid torsion result without full
   resistance is `NOT ASSESSED`, with no utilisation or `<= 100 %` criterion.
   Geometry/partition failure remains a distinct invalid result, and an assessed
   zero resistance remains an honest failure.
2. **Torsion Results view.** The view states why full resistance is not assessed,
   shows `TEd`, the `TRd,max` concrete-strut cap and `TRd,c` as transparency, and
   may show the reinforcement demand as a requirement. It shows no `TRd`,
   utilisation, governing resistance, accepted-resistance angle or PASS/FAIL.
3. **Combined Results.** Missing closed links make the torsion prerequisite and
   every dependent combined physical check `NOT ASSESSED`; no Formula 6.29,
   shared-stirrup or DK-NA aggregate verdict is issued from the unassessed result.
4. **Standard report.** Input wording names the shared links and closed torsion
   loop. The torsion section publishes the same not-assessed reason and concrete
   transparency, without the governing-resistance, utilisation or verdict
   formula blocks.
5. **Audit and Brief reports.** Registers and selected worked examples use the
   same status and do not promote `TRd,max` or stale geometry to a full result.
6. **Manual.** The user guidance distinguishes effective shear legs from the
   one-leg closed torsion loop and states the exact no-links publication rule.
7. No surface calls the informational cap an accepted resistance, capacity,
   governing check or compliant result.

## Acceptance matrix

| ID | Authoritative condition | Required result |
|---|---|---|
| A03-01 | Torsion on; shared links false; stored diameter/spacing positive | Tube/concrete transparency may be retained; full resistance is `NOT ASSESSED`; stored geometry cannot override authority. |
| A03-02 | Torsion on; shared links false; stored geometry zero | Same absent-authority result; `TRd,max` is never promoted to `TRd`. |
| A03-03 | Shared links true; positive one-leg reinforcement; `TRd,s < TRd,max` | Existing stirrup-governing resistance, utilisation and verdict are unchanged. |
| A03-04 | Shared links true; positive one-leg reinforcement; `TRd,max < TRd,s` | Existing concrete-strut-governing resistance, utilisation and verdict are unchanged. |
| A03-05 | Shared links true; one-leg reinforcement zero | Full resistance is `NOT ASSESSED` with the non-positive-reinforcement reason. |
| A03-06 | Shared links true; positive reinforcement; selected resistance zero | Full resistance is assessed as zero and may issue an honest failure. |
| A03-07 | Shared authority missing from a loaded project | It is normalized to exact false and clears any stale true session value; schema remains 25. |
| A03-08 | Shared authority is null, numeric, text or another non-Boolean serialized value | Project load rejects it; runtime never truthiness-coerces it into authority. |
| A03-09 | Authority changes after a completed calculation | Current input signature differs; retained Results/report publication is stale until recalculation. |
| A03-10 | Shear only; links false | Existing `VRd,c` shear path remains available; no reinforced-shear result is invented. |
| A03-11 | Shear and/or torsion; links true | One stored loop is used; shear uses the selected effective leg count and torsion exactly one leg. |
| A03-12 | `torsion_nu_v` true; links false | Closed-detailing credit is not applied and publication does not claim it. |
| A03-13 | Valid single tube; links false | `tube_valid=true`, `full_resistance_assessed=false`, `valid=false`; no `TRd`/utilisation/governs/verdict. |
| A03-14 | Valid subdivision; links false | Per-tube transparency remains; no full-capacity sum, governing sub-tube or verdict. |
| A03-15 | Invalid tube/partition, regardless of link authority | Geometry failure retains its existing distinct invalid reason and precedence. |
| A03-16 | Combined M-V-T requested; links false | Preflight names the missing shared links; combined torsion-dependent checks are `NOT ASSESSED`. |
| A03-17 | Torsion action is exactly zero | Existing `NOT APPLICABLE`/not-evaluated case routing is unchanged. |
| A03-18 | Either supported 2005-family torsion method | The same authority/status rule applies; method equations and defaults are unchanged. |
| A03-19 | No-links result is shown in app, Standard, Audit or Brief | Every surface labels concrete values as transparency and omits full-resistance formulas and verdict language. |
| A03-20 | Current-links positive control is shown in app and reports | Existing full-resistance equations, provenance, precision and verdict remain available. |
| A03-21 | Repository scope is inspected | No schema/version/release, crack, fatigue, Results-Overview redesign, plot-hover, input-reference, plastic-summary or manual-reference-cleanup outcome enters this PR. |

## Focused verification

Development evidence is limited to the affected surfaces:

- direct `tube_torsion` and context tests for exact authority, stale geometry,
  zero reinforcement, zero capacity, both governing branches and both methods;
- Streamlit AppTest controls for widget enablement, session persistence,
  single/subdivided no-links results, current-links compatibility, `nu_v`, stale
  signatures and combined preflight;
- project save/load/resave controls for exact Boolean, absent fallback and
  malformed values without a schema change;
- Results Overview and combined status controls;
- Standard/Audit/Brief report and manual wording/omission controls;
- representative existing shear, torsion, combined and report compatibility
  nodes; and
- Ruff-policy, strict-mypy, compile, ASCII, diff, exact-scope, version and schema
  guards.

The full suite, coverage, package and release qualification remain deferred to
the governed G1/G2 gates under D095-002.

## Explicit exclusions

- No new project key, schema migration or version bump.
- No compatibility-versus-equilibrium torsion classification.
- No change to `TRd,s`, `TRd,max`, `TRd,c`, Formula 6.28, Formula 6.29 or the
  supported method registry.
- No new global verdict, certification, approval or selectable design basis.
- No PR-A04 through PR-A10 behavior.
- No full-suite, packaging or release work in this bounded development PR.
