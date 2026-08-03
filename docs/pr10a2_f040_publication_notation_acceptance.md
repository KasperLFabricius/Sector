# PR-10A2 F040 publication notation acceptance

## Frozen boundary

This slice supplies one shared, trust-aware notation layer for the retained PDF
report and user manual. It changes publication markup only. Numerical values,
solver and trace mechanics, output precision, source identities, verdicts,
layout geometry, pagination, schemas, and application version remain unchanged.

## Trusted engineering inventory

- Scientific forms: lower/uppercase `e`, signed/unsigned exponents, decimal dot
  or comma, space-grouped mantissas, and positive/negative mantissas.
- Scientific suffixes: `%` and `deg`, attached or separated by whitespace.
- Unit powers: isolated `m2`, `cm3`, `mm2`, `mm4`, and compound `mm2/mm` forms.
- Scientific atoms stay together and render as mantissa, multiplication sign,
  base 10, and superscript exponent.
- Existing tags, entities, and complete non-breaking atoms are inert; applying
  the layer repeatedly must produce exactly the same markup.

## Literal identity inventory

Project and author metadata, action-set identities and sources, material names
and descriptions, fatigue spectrum/bin names and descriptions, provenance text,
and trace labels are literal channels. Scientific-looking or unit-looking text
inside those channels remains exactly visible after ReportLab decoding. Escaping
must occur before trusted notation or Greek-token rendering.

## Adversarial closure

- Missing exponents, incomplete signs, embedded identifiers, and suffixed unknown
  words remain inert.
- `%`/`deg` suffix handling is independent of exponent parsing.
- Literal examples include `Bridge 100 m2`, `case 1e-12 %`, decimal-comma science,
  unit powers, Greek-like words, ampersands, and angle brackets.
- The report/manual entry points share the same trusted normaliser.

## Explicit exclusions

- No font, table-width, pagination, continuation, spacing, or equation-layout work.
- No equation IDs, numbering, grayscale, shared publication styling, or preflight.
- No UI-input, persistence, workflow, packaging, or version change.
- No v0.93 roadmap work.
