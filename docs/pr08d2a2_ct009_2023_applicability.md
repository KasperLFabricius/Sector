# PR-08D2a2 CT-009 2023 applicability acceptance

## Boundary

This slice extends the accepted CT-009 `EN 1992-1-1:2023`, edition `2023`,
non-DK route with explicit unsupported-applicability evidence. It changes no
solver, crack-width formula, finite candidate, output adapter or material rule.
The long-term, short-term and aggregate members retain exact order.

Uniform direct tension remains deferred to PR-08D2b. The direct-tension fence is
derived independently from each original reconstructed cracked strain plane by
the accepted serviceability classifier. It therefore controls even when an
unsupported geometry produces no crack candidate. Tendon bond remains deferred.
Danish NA and bridge 2023 routes remain excluded.

## Frozen state matrix

| Reconstructed case | Case branch and scope | Case method | Aggregate |
| --- | --- | --- | --- |
| Refined bending result | `calculated`, `refined-bending` | `sector-en-1992-1-1-2023-refined-bending-replay` | Finite maximum when no required case is `NOT ASSESSED` |
| Uncracked or genuinely inapplicable | `not-applicable` | `sector-en-1992-1-1-2023-crack-width-not-applicable` | `not-applicable` only when no finite or unassessed case exists |
| Unsupported assessed state | `not-assessed` | `sector-en-1992-1-1-2023-crack-width-not-assessed` | Blocking `not-assessed`, with every distinct case reason retained |
| Uniform direct tension | Fails closed before candidate parsing | Deferred | Deferred |
| Tendon participation | Fails closed before numerical replay | Deferred | Deferred |
| Non-converged solver | Accepted explicit failed member | `sector-en-1992-1-1-2023-crack-width-failure` | Not constructed |

Every undefined case publishes no fabricated width, limit, resistance,
utilisation or verdict. A finite sibling cannot mask a required `NOT ASSESSED`
case in the aggregate. Case reasons are preserved exactly; aggregate reasons are
deduplicated in retained case order. All input, output, geometry, material,
dependency and metadata closure from PR-08D2a1 remains unchanged.

## Regression boundary

The accepted PR-08D2a1 calculated and uncracked bundle bytes remain frozen at
SHA-256 `e40416438c1894795e040c820e16d2b04904d196f86fceccba13785278085390`
and `65d17e6ae2eb6a8a9e0a054d7b229c43e15495e2c407568e3a8b46c3e3b4acfb`
for their recorded contexts. Accepted 2004 base, building-DK and bridge-route
bundles remain byte-identical. Sector remains version `0.91`.
