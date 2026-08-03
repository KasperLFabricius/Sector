# PR-08D.1a acceptance: CT-009 base crack width

## Frozen scope

This reslice publishes calculation-trace evidence for the retained
`EN 1992-1-1:2005` selector, whose implemented solver edition is `2004`. It
contains two ordered members, long-term and short-term, followed by one
aggregate. It replays accepted mechanics; it does not change the solver.

The following selectors are explicitly outside this candidate and publish no
CT-009 base trace:

- `DS/EN 1992-1-1 + DK NA`;
- both EN 1992-2 selectors;
- `EN 1992-1-1:2023` refined and direct-tension methods.

They remain sequenced companion work. In particular, this candidate cannot cite
EN 1992-1-1 clauses for an EN 1992-2 calculation and contains no Danish coarse
or cover-dependent mechanics.

## Applicability and identity

The family applies only when the analysis mode is `Elastic` or `Both`, crack
width is requested with an exact Boolean, and the selected code/edition flags
are exactly `EN 1992-1-1:2005`, `2004`, and `dk_na=false`.

The sealed original-input identity retains:

- raw and resolved concrete rings, bars, tendons, coordinates, and areas;
- concrete, reinforcing-steel, and prestressing-steel laws and concrete ID;
- element IDs, material IDs, aligned laws, catalogue order, catalogue names,
  descriptions, presets, and numerical laws;
- long- and short-term actions, modular ratios, concrete modulus, creep,
  tensile strength, diameter selection, bond coefficient, method selector,
  edition, and member selector.

`fatigue_detail_id`, the DK-only `sls_member` value, and the 2023-only
`sls_tendon_xi` value are outside the base mechanics. Their presence, insertion
position, and retained type are pinned, while their values are deliberately
inert.

## Authoritative replay

The trace reconstructs the folded bar/tendon section, per-element modulus,
locked-in tendon prestress, long/short elastic state, cracking path, transformed
properties, effective tension area, reinforcement ratio, mean strain, crack
spacing, every candidate crack width, and governing selection from original
inputs. It uses accepted low-level Sector kernels rather than candidate-selected
governing fields.

The retained output inventory is checked in insertion order and with exact
mapping/list/tuple/scalar types. It includes convergence, cracking factor and
state, `props_un`, conditional `props_cr`, both crack payloads, selected code and
edition when cracked, and `crack_output`. Candidate order/cardinality, element
identity, and every published candidate field are replayed.

Transformed property units are fixed as:

- area: `m2`;
- centroid coordinates: `m`;
- `Ix`, `Iy`, and `Ixy`: `m4` (`second_moment`).

## Provenance

Standard-sourced steps cite only the local
`DS/EN 1992-1-1:2004 + A1:2014 + AC:2010` document:

- 7.3.2(3), Figure 7.1 for the effective tension area;
- 7.3.4(2), Expression (7.9) for mean strain;
- 7.3.4(3), Expression (7.11) for close-centre spacing;
- 7.3.4(4), Expression (7.14) for wide spacing;
- 7.3.4(1), Expression (7.8) for crack width.

Solver reconstruction, geometric clipping, and governing selection remain
project methods. No standard citation is invented for them.

## Result states and exclusions

Calculated members publish finite crack width. Uncracked or unsupported cases
publish an explicit undefined/not-applicable final with no fabricated value.
Non-converged reconstruction publishes one minimal failed member; numerical
failure-only fields are not traversed, while retained inventory/type shape and
the `INVALID` aggregate state remain pinned.

The family publishes no crack-width limit, utilisation, demand/resistance
verdict, compliance statement, generic biaxial crack interaction, DK rule,
bridge rule, report/UI activation, or version change. Sector remains `0.91`.
