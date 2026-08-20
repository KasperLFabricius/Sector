# PR-A02 v0.95 closed-torsion-link authority acceptance

## Exact boundary

- Exact base: `269c18b3cfbd83aa91ec6e321ea80b5ba4f80893`.
- Base tree: `70c3852f629172729ed9c1521caa262adbd972fd`.
- Product version remains `0.94`; project schema remains `25`.
- Owner outcome: `OA095-002` - require current closed torsion links for full
  torsion resistance and make shear-link versus torsion-link semantics explicit
  across input, Results and publication.
- Change family: the headless selection authority for full torsion resistance
  only.

PR-A02 freezes and implements the core authority contract. It deliberately has
no production call site. PR-A03 depends on this slice and owns the atomic
activation through the existing input, Results and publication surfaces. Until
PR-A03 merges, the legacy application route remains byte-for-byte unchanged and
this new selector can be exercised only directly.

## Engineering boundary

The selected 2005-family torsion model derives the transverse and longitudinal
reinforcement demands from the closed thin-walled shear flow in EN 1992-1-1
6.3.2. `TRd,s` is the transverse-reinforcement resistance. `TRd,max` is the
concrete-strut maximum in Formulae 6.29/6.30, and `TRd,c` is retained cracking
transparency. Neither concrete quantity is a standalone full torsion resistance
when current closed torsion links are absent. Torsion links are closed and
anchored under 9.2.3.

This slice does not decide whether a load case is compatibility torsion or
equilibrium torsion. The caller decides whether to request a full torsion
resistance assessment. Once requested, the selector requires current closed-link
authority and positive current transverse reinforcement.

## Authoritative inputs

The new `select_full_torsion_resistance` contract consumes only:

1. `closed_links_present`, an exact built-in Boolean supplied from the current
   input authority;
2. `asw_over_s`, the current one-leg closed-link reinforcement per unit length;
3. the already-calculated `trd_s` transverse-reinforcement resistance; and
4. the already-calculated `trd_max` concrete-strut maximum.

The selector never infers link authority from a positive retained or calculated
`asw_over_s`. A stale positive reinforcement value cannot override an explicit
`closed_links_present=False` state. All three numeric inputs are normalized to
built-in finite non-negative floats. Boolean and text values are not numeric
evidence.

## Frozen selection result

The result is a frozen, slotted `FullTorsionResistanceSelection` with the exact
normalized operands, authority, assessment state, selected resistance,
governing identity and stable reason token.

1. **Current links.** With exact `closed_links_present=True` and finite positive
   `asw_over_s`, full resistance is assessed as
   `min(trd_s, trd_max)`.
2. **Deterministic governing identity.** `TRd,s` governs when it is lower than or
   equal to `TRd,max`; otherwise `TRd,max` governs. Equality therefore retains
   the existing `stirrups (TRd,s)` identity.
3. **No authority.** With exact `closed_links_present=False`, full resistance is
   not assessed even when `asw_over_s`, `trd_s` and `trd_max` are positive.
   `resistance` and `governs` are `None`, and the reason token is
   `closed_links_not_present`.
4. **No current reinforcement.** With exact `closed_links_present=True` but
   `asw_over_s == 0`, full resistance is not assessed. `resistance` and
   `governs` are `None`, and the reason token is
   `closed_link_reinforcement_not_positive`.
5. **Honest zero capacity.** When current positive links are established, a
   finite zero `trd_s` or `trd_max` remains an assessed zero resistance. A later
   demand/utilisation layer may therefore issue an honest failure rather than
   treating zero capacity as missing evidence.
6. **Malformed input.** An omitted authority fails at the required keyword
   boundary. A provided non-Boolean authority or a Boolean, text,
   non-convertible, negative, NaN or infinite numeric operand raises
   `ValueError`. The selector never returns a valid-looking partial result.

`TRd,s`, `TRd,max` and `TRd,c` calculations, strut-angle selection, design-code
edition behavior, units and precision remain unchanged. The selector does not
calculate utilisation or issue PASS/FAIL.

## Acceptance matrix

| ID | Authoritative condition | Required result |
|---|---|---|
| A02-01 | Closed links true; positive `Asw/s`; `TRd,s < TRd,max` | Full resistance is assessed; `TRd,s` and `stirrups (TRd,s)` are selected. |
| A02-02 | Closed links true; positive `Asw/s`; `TRd,max < TRd,s` | Full resistance is assessed; `TRd,max` and `crushing (TRd,max)` are selected. |
| A02-03 | Closed links true; positive `Asw/s`; equal resistances | The equal resistance is assessed and the stirrup identity wins deterministically. |
| A02-04 | Closed links false; positive stored/current reinforcement and both positive capacities | Full resistance is not assessed; concrete crushing is not promoted to `TRd`. |
| A02-05 | Closed links false; zero reinforcement | Full resistance is not assessed with the absent-authority reason. |
| A02-06 | Closed links true; zero reinforcement | Full resistance is not assessed with the non-positive-reinforcement reason. |
| A02-07 | Closed links true; positive reinforcement; either resistance is zero | Full resistance is assessed as zero with the correct governing identity. |
| A02-08 | Authority is omitted | Required keyword raises `TypeError`; no default authority exists. |
| A02-09 | Authority is `None`, integer, string or NumPy Boolean | `ValueError`; no truthiness coercion. |
| A02-10 | `Asw/s` is Boolean, text, non-convertible, negative, NaN or infinity | `ValueError`; no partial selection. |
| A02-11 | Either resistance is Boolean, text, non-convertible, negative, NaN or infinity | `ValueError`; no partial selection. |
| A02-12 | Supported integer/real scalar inputs | Result fields are normalized built-in floats. |
| A02-13 | Returned result is inspected or an input object is reused | Result is frozen/slotted and input objects are unchanged. |
| A02-14 | Repository runtime before PR-A03 | New selector has no non-test call site; existing application/report behavior is unchanged. |

## Focused verification

PR-A02 provides only bounded development evidence:

- direct selector controls for both governing branches, equality, absent links,
  zero reinforcement and honest zero capacity;
- exact-Boolean and malformed/non-finite numeric mutation matrices;
- normalization, frozen-result and no-mutation controls;
- a static zero-call-site/scope check;
- the existing retained torsion-formula compatibility node; and
- cheap AST/compile, Ruff/policy, strict-mypy, ASCII, version, schema, diff and
  exact-scope guards.

Full repository, coverage, package and release qualification remain deferred to
G1/G2 by D095-002.

## Explicit exclusions

- No application call site, input widget, Results view, report, manual or
  project-persistence change; PR-A03 owns those semantics and activation.
- No new persisted key and no schema or migration change.
- No change to `TRd,s`, `TRd,max`, `TRd,c`, longitudinal reinforcement,
  strut-angle or combined Formula 6.29 calculations.
- No compatibility-versus-equilibrium torsion classification.
- No global verdict, certification, approval or selectable design-basis claim.
- No version, workflow, package or release change.
- No PR-A01 or PR-A04 through PR-A10 outcome enters this slice.
