# PR-13A1B F-013 bridge typed-failure acceptance

## Base and purpose

This slice starts from accepted `main` commit
`f133ebae880b27e07a71586a0aea8fa920306e79`. It closes the retained bridge
kernel/result boundary identified by F-013 without changing any bridge formula,
method, citation, warning, finite result, or verdict.

The boundary must convert expected input and finite-arithmetic failures into
typed, family-local failure records. An unexpected implementation defect must
still propagate. One invalid bridge family must not suppress an independent
valid family or the ordinary section analysis.

## Exact family identity and order

The three optional families remain in this insertion order:

1. `brittle_method_b`, from `bridge_brittle_base`;
2. `box_walls`, from `bridge_box_walls_base`;
3. `minimum_crack_reinforcement`, from `bridge_minimum_crack_base`.

An empty table is inactive and produces neither a calculation nor a failure.
The selected method family remains one of the exact values in
`sector.bridge.METHODS`. An unknown value is an unsupported-standard failure
and produces no bridge calculations.

## Original-input inventory

The raw-input contract, column order, duplicate handling, missing-value rules,
and persistence identity are owned by PR-13A1A-R2 and remain unchanged.

For every active row, the numerical boundary reconstructs the following
original values before calculating or publishing anything:

- Method B: `region_id`, `m_rep_knm`, `z_s_m`, `f_yk_mpa`,
  `as_provided_mm2`;
- box wall: `wall_id`, `cot_theta`, `v_ed_kn`, `v_rd_max_kn`,
  `t_ed_equivalent_kn`, `t_rd_max_equivalent_kn`;
- minimum crack reinforcement: `component`, `act_mm2`, `k_c`, `k`,
  `fct_eff_mpa`, `sigma_s_mpa`, `as_provided_mm2`,
  `restrained_shrinkage`.

IDs remain nonblank and unique within their family. Components remain exactly
`web` or `flange` after case normalization. Every numerical input is a real,
finite value; every denominator, material strength, geometry factor, area, and
provided reinforcement value retains its existing positive constraint.
`restrained_shrinkage` remains a concrete Boolean.

## Candidate-output inventory

The successful top-level payload remains:

- `selected_standard`;
- `scope`;
- `calculations`, in exact active-family order.

It gains `failures`, an ordered tuple of typed failure records. Every record
contains exactly:

- `family`: the calculation-family identity, or `selected_standard`;
- `table_key`: the owning input table key, or `bridge_standard`;
- `state`: `INVALID` or `UNSUPPORTED`;
- `code`: `INVALID_INPUT`, `NUMERICAL_FAILURE`, or
  `UNSUPPORTED_STANDARD`;
- `message`: a stable, user-readable explanation.

Successful Method-B output retains `method`, `equation`, `source`,
`selected_standard`, `warning`, and `rows`. Each row retains `region_id`,
`m_rep_knm`, `z_s_m`, `f_yk_mpa`, `as_required_mm2`,
`as_provided_mm2`, `utilisation`, and `status`.

Successful box-wall output retains `method`, `equation`, `source`, `rows`, and
`warnings`. Each row retains `wall_id`, `cot_theta`, `v_ed_kn`,
`v_rd_max_kn`, `t_ed_equivalent_kn`, `t_rd_max_equivalent_kn`,
`utilisation`, and `status`.

Successful minimum-crack output retains `method`, `equation`, `source`, and
`rows`. Each row retains `component`, `act_mm2`, `k_c`, `k`,
`fct_eff_mpa`, `sigma_s_mpa`, `as_provided_mm2`,
`restrained_shrinkage`, `fct_eff_used_mpa`, `as_required_mm2`,
`utilisation`, and `status`.

Every published numerical input is the independently normalized original
value. Every computed value is finite. `status` is published only after a
finite utilization is reconstructed from the retained kernel.

## Failure states and dependency graph

Expected domain validation raises `BridgeInputError`. Finite-arithmetic
underflow, overflow, zero denominators created by finite positive operands, or
non-finite computed results raise `BridgeNumericalError`.

The adapter catches only these two domain exceptions, independently for each
active family. It must not catch `RuntimeError`, `AssertionError`, `KeyError`,
or any other unexpected exception class.

For each active family the dependency graph is:

1. original table and retained row identity;
2. field-specific type, finiteness, sign, range, and duplicate validation;
3. accepted low-level numerical kernel in its existing arithmetic order;
4. finite computed result and utilization;
5. genuine demand/resistance `PASS` or `FAIL` verdict;
6. Streamlit and report publication.

Failure at steps 2-4 publishes one typed failure record and no calculation,
resistance, utilization, or verdict for that family. Other valid families
continue through their complete graph. An unsupported standard stops all
bridge families before any candidate numerical field is parsed.

The Streamlit view and PDF report identify the failed family and state without
inventing a result. Failure-only rendering requires no omitted numerical
candidate field. A bridge failure remains active even when no bridge
calculation succeeds, and it cannot suppress otherwise valid section results.

## Adversarial evidence required

- the retained finite benchmark for every family is unchanged;
- the documented Method-B positive-finite denominator underflow is a typed
  numerical failure rather than an uncaught `ZeroDivisionError`;
- multiplication overflow, division overflow, and nonzero quotient underflow
  never publish non-finite or zero-fabricated engineering results;
- every family can fail while both valid siblings remain published in order;
- malformed input and an unknown standard have their exact typed states and
  codes;
- oversized integers retain stable bridge and project identity before their
  field-specific typed rejection, without pandas coercion or JSON drift;
- monkeypatched unexpected exceptions propagate through the adapter and the
  application boundary;
- Streamlit and report surfaces render typed failures and retain valid sibling
  calculations;
- isolated strict typing, selected Ruff rules, compile/import checks, ASCII,
  version, base, scope, and rejected-ancestry guards pass.

## Explicit exclusions

No bridge equation, arithmetic order, tolerance, method, standard edition,
source, citation, warning policy, ordinary finite result, custom positive
finite input, coverage/compliance route, material law, section solver, other
input family, persistence schema, calculation trace, package, workflow,
dependency gate, signing, release, application version, PR-14, or v0.93 change
is included. Remaining non-bridge F-013 work and F-012 staged CI gates remain
separate later PR-13 slices.
