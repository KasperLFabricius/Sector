# PR-13A1 F-013 typed bridge-boundary acceptance

Exact base: `89fbc4a9713727093f453d0af7ffdce2dae17393`.

Sector remains version `0.91`. This slice owns the retained independent bridge
input, kernel-result, and application-result boundary plus the PR-13 carry-over
defect. It is one F-013 failure-transparency class, not a bridge-compliance or
new-mechanics slice.

## Retained method identity

The three selectable method-family identities and their order remain:

1. `Independent component calculations`;
2. `DS/EN 1992-2:2005 + AC:2008`;
3. `DS/EN 1992-2 DK NA:2015`.

The retained component calculations remain:

- optional brittle Method B, `As,min = Mrep / (zs fyk)`, with its existing
  DS/EN 1992-2:2005 6.1(109)-(110) source and Danish-selection warning;
- separate box-wall shear/torsion interaction,
  `VEd/VRd,max + TEd,wall/TRd,max,wall`, with its existing
  DS/EN 1992-2:2005 6.3.2(101)-(104) plus AC:2008 source;
- separate web/flange minimum crack reinforcement,
  `As,min = kc k fct,eff Act / sigma_s`, with its existing
  DS/EN 1992-2:2005 7.3.2(102)-(105) source.

No equation, arithmetic order, tolerance, warning trigger, citation, ordinary
finite result, row verdict, or custom positive-finite input is changed.

## Frozen input and output inventory

The brittle family retains region ID, `Mrep`, `zs`, `fyk`, provided area,
selected method family, required area, utilization, row status, equation,
source, and warning.

The box-wall family retains wall ID, `cot(theta)`, shear action/resistance,
torsion-equivalent action/resistance, utilization, row status, equation,
source, and warnings. Supplied angles remain unmodified.

The minimum-crack family retains component identity, `Act`, `kc`, `k`,
`fct,eff`, `sigma_s`, provided area, restrained-shrinkage flag, used
`fct,eff`, required area, utilization, row status, equation, and source.

The boundary types pin the method identity, calculation keys, row fields,
status values, failure codes, and application payload. The three critical
modules must pass strict mypy with no errors.

## Failure-first contract

All original numerical inputs are validated for real type, finiteness, sign,
and range before their result is published. Every positive-only intermediate
and every division is checked before a result row is constructed.
Blank-row classification uses the original cells before canonicalization, so a
malformed numeric or Boolean value cannot be normalized away and filtered as an
inert empty row. A genuinely empty row remains inert, while duplicate table
columns are rejected before canonicalization.

Finite positive inputs therefore have exactly two permitted outcomes:

- the retained finite numerical result; or
- a typed `NON_FINITE_RESULT` failure naming its causal field.

Malformed original input produces typed `INVALID_INPUT` evidence. Expected
conversion failures retain Python exception chaining. The application payload
publishes `state`, `family`, `code`, `field`, `message`, and `cause_type`; it
publishes no fabricated resistance, utilization, row verdict, or large finite
substitute for that failed family.

Expected `BridgeCalculationError` instances are the only failures converted to
`INVALID`. An unexpected implementation exception propagates unchanged.

## Independent-family boundary

Each active bridge family is evaluated through its own typed boundary. A
corrupt brittle family does not remove a valid box-wall or minimum-crack result,
and a valid sibling does not conceal the failed family. Streamlit and the PDF
report show every typed failure and continue to show independently valid
component results.

## Adversarial and retained evidence

The focused oracle covers:

- the exact carry-over denominator-underflow case;
- finite overflow in box-wall utilization;
- finite overflow in minimum crack reinforcement;
- originating input-conversion cause preservation;
- malformed-row filtering, duplicate-column rejection, and retained
  Boolean-type fencing;
- per-family failure isolation with a valid sibling result;
- propagation of an injected unexpected runtime fault;
- all retained ordinary bridge numerical benchmarks.

The directly affected publication oracle proves a typed invalid family contains
no fabricated row while a valid sibling remains visible. Existing report
bridge-method and product-identity assertions remain controlling.

## Explicit exclusions

No bridge coverage aggregate, applicability matrix, approval route, generic
cross-method interaction, compliance verdict, standard implementation,
material law, section solver, project schema, persistence migration,
calculation trace, packaging, workflow, signing, release, application-version,
PR-14, or v0.93 change is included. Other F-013 engineering catch boundaries
and all F-012 CI gates remain later PR-13 slices.
