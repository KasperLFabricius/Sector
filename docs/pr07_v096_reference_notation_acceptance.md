# PR-07 acceptance - terminology, references and strain notation

## Frozen base and product boundary

- Base: `1cc32c438542f57cf7fb25d47848f8abeeaf46bb` (`origin/main`
  after PR-06).
- Base tree: `3541bf5647fd1ba69b0b1e814c3bdf45f67cb674`.
- Decision owners: D096-014, D096-015 and D096-016.
- Product version remains `0.95`; project schema remains `27`.

PR-07 changes user-facing sources, terminology and strain-unit notation. It
does not change an equation, selected method, numerical input, applicability,
result selection, comparison, profile-depth rule, persistence field, schema,
package or release surface.

## Exact reference contract

The existing edition-bound input-guidance registry remains the single source
for the creep coefficient and the three detailing controls. The UI tooltip,
manual and every applicable report profile must publish the same selected
source. A curve-only concrete preset remains project-defined; Sector states
that no Eurocode source is inferred.

| Input or material route | Required publication source |
|---|---|
| First-generation creep coefficient | DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 3.1.4 and Annex B.1; the Danish preset additionally identifies DK NA:2024, 3.1.4(1)-(2). |
| 2023 creep coefficient | DS/EN 1992-1-1:2023, 5.1.5, Table 5.2 and Annex B.5. |
| Minimum reinforcement | The exact first-generation/Danish or 2023 source already registered for the selected Detailing edition, including all implemented clauses and tables. |
| Shear/torsion link detailing | The exact first-generation/Danish or 2023 ratio and spacing source already registered for the selected Detailing edition. |
| Reinforcement clear spacing | The exact first-generation/Danish 8.2(2) or 2023 11.2(2) source already registered for the selected Detailing edition. |
| 2023 concrete design law | DS/EN 1992-1-1:2023, 5.1.6(1), Formulae (5.3)-(5.4), and 8.1.1(2)-(3) with 8.1.2(1), Formula (8.4), as applicable. |
| 2023 reinforcing steel design law | DS/EN 1992-1-1:2023, 5.2.4(1)-(3), Formula (5.11) and Figure 5.2. |
| 2023 prestressing steel design law | DS/EN 1992-1-1:2023, 5.3.3(1)-(3), Formula (5.12) and Figure 5.3. |

The 2023 edition remains a published project-adoption option without a Danish
National Annex. Project-defined material values are not assigned a source from
numerical similarity.

## Neutral calculation-language contract

Algorithmic convergence is described as solved, converged, selected or
retained, not accepted. Result records and figures report information, not
published evidence or certificates. A shared stirrup is governed by an enabled
selection, not an authority. A zero crack-width limit is described as no limit
comparison.

The product-identity limitation remains explicit: Sector does not certify,
approve or sign off engineering. PASS and FAIL remain available only for an
implemented comparison; changing surrounding wording does not change any
comparison or status precedence.

## Strain-unit contract

Manual, HTML and report user text uses the per-thousand sign rendered from the
ASCII-safe Unicode identity `U+2030`. The displayed examples are therefore
`2.0` followed by `U+2030`, not the words formerly used for that unit. Internal
keys such as `strain_permille`, calculation comments and parser tokens remain
unchanged. PDF extraction, HTML text and the bundled font must preserve the
visible sign.

The concrete input help is corrected to the values actually entered by the
material law: 2.0 per thousand at peak stress and 3.5 per thousand at ultimate
strain for normal-strength concrete. This is a display/help correction only;
the stored defaults and material-law fractions are unchanged.

## Acceptance matrix

| ID | Condition | Required result |
|---|---|---|
| RN96-01 | Creep input is active | UI, manual and report agree with the selected concrete-preset source; project-defined presets remain explicitly uncited. |
| RN96-02 | A detailing checkbox is active | UI, manual and report agree with the selected Detailing-edition source for that exact check. |
| RN96-03 | A 2023 material preset is reported | Concrete, reinforcing-steel and prestressing-steel references use the exact 2023 edition and applicable clauses/formulae. |
| RN96-04 | User-facing calculation text is scanned | Approval-like state, evidence, certificate and authority phrases are replaced by neutral calculation descriptions; the product-identity disclaimer remains. |
| RN96-05 | Crack width has a zero user limit | The result is described as calculated with no limit comparison; no comparison or verdict is manufactured. |
| RN96-06 | Manual PDF/HTML and reports are rendered | Visible and extracted strain units use `U+2030`; the former written-out unit is absent from user text. |
| RN96-07 | Concrete input help is inspected | The normal-strength values are 2.0 and 3.5 per thousand and still map to 0.002 and 0.0035 internally. |
| RN96-08 | Scope and version are inspected | Numerical results, profile depth, schema 27 and product version 0.95 are unchanged. |

## Verification order

1. New cross-surface reference, terminology and notation adversarial tests.
2. Existing design-standard, material-preset, manual, report, result-
   presentation and Streamlit tests affected by the wording contract.
3. Targeted compile, Ruff, ASCII-source, version, schema and diff guards.
4. Real manual PDF/HTML and Brief/Standard/Audit generation, extracted-text
   checks and focused raster inspection.
