# Sector product identity

Sector is a transparent structural-analysis and design calculation tool. It is
not a compliance-management, certification, sign-off, authority-approval or
code-completeness system.

The engineer controls the calculation methods, action cases and engineering
coefficients. A selected standard supplies equations, named methods,
defaults/ranges, citations and warnings. It does not make Sector a complete
implementation of a Eurocode, national annex, bridge-owner requirement or
project design basis.

Positive finite custom values are calculation inputs, including material partial
factors such as 0.5 or 2.0. Sector may warn when a value differs from a selected
method's default. It must not clamp, replace or reject that value merely because
of the difference. Inputs are rejected only when malformed or when they make the
selected mathematics undefined.

That rule includes the direct concrete tensile factor `gamma_ct` used by the
retained torsional-cracking calculation. Its selected-method default is 1.50
for EN and 1.70 for DK/NA; any positive finite user value remains the actual
solver, project and report input. Boolean scalars, including library Boolean
types that numerically coerce to zero or one, are malformed numerical inputs
and are rejected rather than treated as coefficients.

PASS/FAIL is reserved for an implemented demand-versus-resistance equation.
Stresses, crack widths and other output-only quantities carry no acceptance
verdict when no criterion is supplied. An optional user-specified crack-width
criterion produces only `WITHIN USER-SPECIFIED LIMIT` or
`EXCEEDS USER-SPECIFIED LIMIT`, publishes the criterion source and does not
become a code-compliance conclusion. Sector does not issue a global compliance
verdict.

Published results retain only the provenance needed to reproduce the
calculation: application/source version, actual inputs, selected
method/equation, action identity and result freshness. Stale, corrupt or
input-mismatched results remain rejected.

Sector 0.93 is the current internal version and uses current-only project
schema 24. Sector 0.93 rejects released Sector 0.92 schema 23 rather than
migrating or silently dropping inputs. Earlier app/project/schema versions and
their compliance, cover-calculator or authority metadata remain deliberately
unsupported and are not carried forward. Its portable Windows ZIP is unsigned;
no trusted-publisher reputation or administrator approval is claimed.

Sector does not infer semantic bridge regions, walls, webs or flanges. A
calculation that cites a bridge source remains bounded to its implemented
equation and entered section actions; it is not a complete bridge check.

This contract is an acceptance criterion for every product change. A QA finding
cannot expand Sector's product identity without explicit owner direction.
