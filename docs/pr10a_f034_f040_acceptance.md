# PR-10A acceptance matrix: notation identity and torsion provenance

Base: exact accepted `main` at `563d107d223541703f848e44c07ddfbcc22bd2d7`.

## Frozen scope

- F-034: identify the transverse closed-link torsion expression as derived from
  EN 1992-1-1 Formula (6.27) together with transverse equilibrium in Formula
  (6.8). Retain Formula (6.28) solely for longitudinal torsion reinforcement.
- F-040: use one ASCII-source ReportLab notation layer for scientific notation,
  atomic numeric tokens, and unit powers in the report and manual.
- Preserve literal project, material, section, member, action-set, spectrum, and
  trace identities. A bare identity such as `m2`, `cm3`, or `mm4` is never
  interpreted as an engineering unit.

## Acceptance inventory

1. Finite scientific values publish as `mantissa x 10` with a typographic
   superscript exponent and remain one non-breaking token.
2. Numeric tokens do not split across lines; repeated application of the
   notation layer is idempotent.
3. Unit powers convert only in authored formula/manual content and trusted table
   headers.
4. Untrusted report prose and table bodies retain audit identities exactly even
   when an identity resembles a value and unit, such as `Bridge 100 m2`.
5. UI, report, manual, torsion module documentation, and CT-007 source metadata
   distinguish transverse Formulae (6.27)/(6.8) from longitudinal Formula
   (6.28).
6. Existing mechanics, values, trace dependency graphs, output cardinality,
   verdicts, and selected standards remain unchanged.

## Explicit exclusions

F-019/F-032/F-037 pagination, responsive table geometry, and font-floor work is
owned by PR-10B. Equation, figure, table numbering and PDF preflight are PR-11.
There is no solver/formula/schema/version change, no PR-11+ work, no restored
legacy or PR-07 path, and no v0.93 implementation.
