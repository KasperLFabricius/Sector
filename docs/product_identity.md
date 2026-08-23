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
Stresses and other output-only quantities carry no acceptance verdict. For an
Elastic action that requests crack width, that calculation remains optional.
Independent long-term and short-term crack-width limits are user-specified: a
0 mm value leaves that duration's calculated width without comparison, while a
positive value produces only `WITHIN USER-SPECIFIED LIMIT` or
`EXCEEDS USER-SPECIFIED LIMIT` and publishes the matching source. This does not
become a code-compliance conclusion. Sector does not issue a global compliance
verdict.

Published results retain only the provenance needed to reproduce the
calculation: application/source version, actual inputs, selected
method/equation, action identity and result freshness. Stale, corrupt or
input-mismatched results remain rejected.

Sector 0.96 is the current internal product identity and uses project schema
27. Schemas 25 and 26 have bounded migrations. For schema 25, the former single
permitted crack width is copied to the independent long-term and short-term
ordinary inputs, and is preserved separately as the Formula 7.100 NA operand
only when that heightened calculation was enabled. Schemas 25 and 26 receive
the former fixed DS/EN 1992-1-1:2023 shear partial factor as the explicit
`gamma_V = 1.40` input. Zero means no ordinary crack-width comparison and is
never promoted to the heightened operand. Schema 24 and future schemas remain
unsupported. Earlier compliance, cover-calculator or authority metadata is not
carried forward. Its portable Windows ZIP is unsigned; no trusted-publisher
reputation or administrator approval is claimed.

Sector does not infer semantic bridge regions, walls, webs or flanges. A
calculation that cites a bridge source remains bounded to its implemented
equation and entered section actions; it is not a complete bridge check.

This contract is an acceptance criterion for every product change. A QA finding
cannot expand Sector's product identity without explicit owner direction.
