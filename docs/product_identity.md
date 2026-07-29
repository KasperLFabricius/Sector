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

PASS/FAIL is reserved for an implemented demand-versus-resistance equation.
Stresses, crack widths and other output-only quantities carry no acceptance
verdict. Sector does not issue a global compliance verdict.

Published results retain only the provenance needed to reproduce the
calculation: application/source version, actual inputs, selected
method/equation, action identity and result freshness. Stale, corrupt or
input-mismatched results remain rejected.

This contract is an acceptance criterion for every product change. A QA finding
cannot expand Sector's product identity without explicit owner direction.
