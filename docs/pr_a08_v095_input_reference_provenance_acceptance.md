# PR-A08 v0.95 input-reference provenance acceptance

## Outcome and boundary

PR-A08 gives the creep-coefficient input and the three reinforcement-detailing
checkboxes an exact source for the edition already selected in Sector. The
source is input guidance: it explains the implemented input or check without
granting a new calculation route or deciding project applicability.

The creep source follows the existing concrete preset because the coefficient
is a concrete-property input shared by Elastic and Fatigue calculations. A
named stress-strain curve without a Eurocode edition remains project-defined;
Sector infers no standard from its numerical values. The detailing sources
follow the existing Detailing edition.

This slice adds no design-basis selector, solver route, derived coefficient,
criterion, status, persistence field, schema field, report field, global
verdict or product-version change. PR-A08 adds only source help to the existing
selectors. Their established behavior remains: a concrete preset may prefill
material values, and the Detailing edition selects its existing calculation
rules. The help introduces no new side effect, never changes the entered creep
coefficient and does not alter checkbox state or entered geometry.

## Creep-coefficient sources

- The first-generation recommended-value preset cites DS/EN 1992-1-1:2004 +
  A1:2014 + AC:2010, 3.1.4 and Annex B.1.
- The Danish preset also cites DS/EN 1992-1-1 DK NA:2024, 3.1.4(1)-(2). It says
  that `phi = 3` is conditional and that Sector does not infer whether creep is
  decisive or whether recycled-aggregate documentation is required.
- The 2023 preset cites DS/EN 1992-1-1:2023, 5.1.5, Table 5.2 and Annex B.5.
  Its existing basis disclosure says project adoption is required and no
  Danish National Annex is applied.
- A curve-only concrete preset states that it is project-defined and that no
  Eurocode source is inferred.
- Every route asks for the final coefficient. Sector does not derive humidity,
  notional size, age at loading, duration or the Table 5.2/Annex B operands.

## Detailing-checkbox sources

- Minimum reinforcement cites first-generation 9.2.1.1(1), Formula (9.1N),
  and 9.3.1.1(1)-(2), including the Danish 9.2.1.1(1) source when selected. The
  Danish high-beam-web provision is explicitly outside Sector's implemented
  modelled-direction check. The 2023 source is 12.2(2), Formulae (12.1)-(12.2)
  and Table 12.2.
- Shear/torsion link detailing cites the implemented first-generation link
  ratio and spacing clauses, including DK NA:2024 9.2.2(5), Formula (9.5N NA),
  when selected. The 2023 source is 8.2.1(2), 12.2(4), Tables 12.1 and 12.2,
  12.3.3 and 12.4.2.
- Clear spacing cites first-generation 8.2(2), including its unchanged Danish
  source when selected, or 2023 11.2(2). Anchorage, laps, bundles, cover and
  construction access remain outside this pairwise geometry check.
- The 2023 help repeats the existing published-reference disclosure: project
  adoption is required and no Danish National Annex is applied.

## Acceptance matrix

| ID | Condition | Required result |
|---|---|---|
| A08-01 | First-generation concrete preset is selected | Creep help cites 3.1.4 and Annex B.1 and does not claim a Danish National Annex. |
| A08-02 | Danish concrete preset is selected | Creep help cites DK NA:2024 3.1.4(1)-(2), identifies `phi = 3` as conditional and makes no applicability inference. |
| A08-03 | 2023 concrete preset is selected | Creep help cites 5.1.5, Table 5.2 and Annex B.5 and discloses project adoption/no Danish National Annex. |
| A08-04 | Curve-only concrete preset is selected | Help says project-defined and no Eurocode source is inferred. |
| A08-05 | Minimum-reinforcement checkbox is inspected | Help follows the exact Detailing edition, cites the implemented clauses and preserves the Danish high-beam-web exclusion. |
| A08-06 | Link-detailing checkbox is inspected | Help follows the exact Detailing edition and cites the implemented link-ratio and spacing clauses. |
| A08-07 | Clear-spacing checkbox is inspected | Help follows the exact Detailing edition and states the bounded pairwise-geometry scope. |
| A08-08 | Help routing is inspected | Creep provenance follows the concrete preset without changing the entered coefficient; detailing provenance follows the selected edition without adding calculation state. Existing preset-prefill and edition-routing behavior remains. |
| A08-09 | Repository scope is inspected | No new basis, solver route, schema, persistence, report, status or product-version change is included. |

## Focused verification

- design-standards tests pin every basis/key registry entry and exact source;
- focused Streamlit AppTests pin live help changes and retained input state;
- manual tests pin current-only user guidance;
- programme-contract tests pin this acceptance matrix and the no-expansion
  boundary; and
- targeted static checks pin the two-file runtime change and unchanged product
  identity.

The full suite, coverage, portable package and release qualification remain at
the governed G1/G2 gates.
