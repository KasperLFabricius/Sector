# PR-03 Sector v0.93 textbook-calculation publication acceptance

Status: accepted and merged as PR #384. Reviewed head
`9fdb4839fa2778e67e6d2c2324640f1c0755ff6c` passed Sector QA run
`31335521261`; squash `115d78a5fec33bc6d7a614f6a526a17ab32c22e2`
has accepted tree `14ff5582bb6669d902e0ae4be32fd3bd9d626c84`.

## Exact accepted base

- Repository revision: `b328144abf175e0025c796da929dfe01fd843293`
- Repository tree: `b2edde56dc0b37dd19e3250011d04b1a3257f6cc`
- Programme branch: `codex/pr03-v093-textbook-calculations`
- Governing identity: [Sector product identity](product_identity.md)
- Living programme: [Sector v0.93 PR programme](v093_pr_programme.md)
- Trace-retirement authority: [PR-11D1 reconciliation](pr11d1_trace_retirement_reconciliation.md)

The base revision is the exact squash merge of PR-02. Its tree is identical to
the accepted PR-02 candidate tree.

## Owner-confirmed objective

PR-03 makes Sector's existing calculations readable as worked textbook examples.
A reader who has not used the formula before must be able to follow the entered
values, selected method, preparation, symbolic equation, numerical substitution,
interim values, governing branch and final result in the output report. The
manual receives worked or explanatory content only where it helps a reader learn
the already implemented method.

PR-03 does not add an engineering calculation, check, acceptance criterion,
standard option or solver method. Existing final numerical results remain
unchanged unless a separately proven defect is discovered and owner scope is
updated explicitly.

## Governing-example density rule

Every calculated case remains in the consolidated result overview and compact
family summaries. A complete textbook derivation is published only once for the
globally governing or extremal result in each calculation family. When a family
has independent criteria, the report may publish one governing example for each
materially different criterion, but it does not repeat the same derivation for
every load case.

For the first-generation DK/NA crack-width method, fine and coarse reinforcement
systems are distinct calculation branches. Sector therefore publishes exactly
one globally largest fine-system crack-width example and one globally largest
coarse-system crack-width example across all elastic cases. Other crack methods
publish one globally governing crack-width example. Fatigue follows the same
principle separately for the governing reinforcement and governing concrete
criterion because those checks may occur in different spectra.

Publication selection is deterministic and uses only retained, applicable final
values. Invalid results, NaN and negative infinity cannot suppress a valid
worked example. A valid demand/resistance failure with positive-infinite
utilisation remains the governing result; when its retained state cannot support
a complete derivation, Sector states that the governing worked calculation is
unavailable rather than substituting a less critical case. If no valid completed
result exists for a family, Sector publishes no invented derivation.

## Binding trace-retirement boundary

The complete calculation-trace subsystem from the previous programme's PR-08
was deliberately retired. PR-03 must not restore it under a different name.
Accordingly this PR adds none of the following:

- a cross-family calculation-trace or calculation-evidence data contract;
- a generic calculation DAG, recorder, tolerant builder or parallel evaluator;
- a trace switch, trace viewer, trace workspace, trace appendix or trace mode;
- a top-level trace/evidence payload in calculation results;
- persisted calculation history, a separate trace seal or a project-schema key;
- raw iteration histories, angle arrays, integration bands or search boxes; or
- a best-effort trace that can disagree with the accepted calculation result.

PR-03 does not add iteration or evaluation counters solely for publication.

The existing result objects are the only numerical authority. The existing
trace-retirement tests remain active and PR-03 adds a focused guard proving the
retired product surfaces remain absent.

## Minimal implementation rule

Most required values already exist in the current results and report tables.
PR-03 first uses those values directly. Where a meaningful interim value is
currently local to a solver and is then lost, the owning family result gains the
smallest explicit named field or family-specific immutable result record needed
to retain it. No generic cross-family recorder is introduced.

This means, for example:

- missing crack-spacing coefficients stay with the existing crack result;
- a final elastic equilibrium residual, when needed to explain validity, stays
  with the existing elastic result;
- an accepted plastic governing-point identity stays with the existing plastic
  result; and
- a governing fatigue criterion or fibre identity stays with the existing typed
  fatigue result.

Report code may extract, order, round and format retained result fields. It may
not rerun a material law, recompute section response, repeat a numerical search,
derive an omitted operand from rounded values or choose a governing candidate.
If a required value is absent, publication fails closed or states that the
calculation is not available; it does not invent the value.

Optional constitutive-law figures are a narrowly bounded presentation exception:
they may sample the already selected law only to draw its curve. Those plot
samples are not calculation results, numerical evidence or a substitute for a
retained worked-calculation value. Figures may not select a branch, change a
result or supply an operand to report text or equations.

## Textbook publication sequence

For each selected governing/extremal existing calculation the report presents,
as applicable:

1. the engineering question;
2. the exact Given data, units, sign convention and selected method;
3. numbered preparation calculations;
4. the symbolic equation, source and short branch explanation;
5. numerical substitution in the same operand order;
6. the interim value and every material min, max or cap candidate;
7. a compact numerical-solution summary where the existing solver is iterative,
   limited to the method, declared range/tolerance or selection rule, accepted
   engineering state and final residual/gap already retained or needed to
   establish validity;
8. the final result and an optional bounded criterion only where one exists; and
9. a plain-language interpretation and unassessed scope.

Crack spacing is an example, not the scope limit. The same reading standard
applies across the existing geometry/material/prestress, plastic, elastic,
ordinary crack-width, detailing, shear, torsion, combined M-V-T and fatigue
calculations. PR-06 later publishes its new crack comparison and heightened
Formula 7.100 NA calculation in the same style.

## Internal implementation slices

PR-03 is one GitHub pull request developed through bounded green commits:

1. freeze the live-equation/publication inventory and the no-trace boundary;
2. complete shared geometry, material and prestress worked calculations;
3. complete plastic and elastic worked calculations;
4. complete ordinary crack-width and detailing worked calculations;
5. complete shear, torsion and combined M-V-T worked calculations;
6. complete reinforcement and concrete fatigue worked calculations;
7. integrate the report and relevant manual examples, remove publication-side
   engineering recomputation and close the family inventory; and
8. perform semantic, independent numerical, rendered and full exact-head gates.

Each family commit carries its retained result fields, adapter exposure, report
publication, governing-only selection and focused tests together. PR-03 does
not add unused intermediate fields for later consumption.

Only directly affected family tests run after a small commit. The full suite and
unsigned Windows QA-package gate run once at PR closeout and again on GitHub.

## Formula and report acceptance

Acceptance requires:

- every used live equation has a symbolic relation, numerical substitution,
  result, unit, source and branch/applicability note where applicable;
- theory relations remain clearly distinguished and may remain symbolic;
- every substitution value comes from an entered/canonical input, an earlier
  displayed step or a retained existing-family result field;
- independent hand calculations reproduce every newly exposed interim value;
- poison tests build reports from completed payloads while solver,
  material-law and governing-selector functions are patched to raise;
- numerical solution summaries show only the method, declared range/tolerance
  or selection rule, accepted state and final residual/gap already retained or
  needed to establish validity;
- no raw debug sequence or retired trace product surface appears;
- formula blocks remain together, readable and unclipped in rendered PDFs; and
- non-governing cases remain in compact summaries without duplicate full worked
  chapters, with exactly one fine and one coarse DK/NA crack example; and
- the final calculation-family publication inventory has no unexplained live
  equation or final result gap.

PR-07A later supplies the constrained Eurocode-style visual equation renderer.
PR-07B later supplies Brief, Standard and Audit density policies. PR-03 uses the
current report system to make the complete default output human-followable now;
later presentation changes must not alter its calculation values.

## Identity and exclusions

Sector remains a transparent calculation tool. A worked derivation does not
create a certificate, approval, code-completeness claim, global compliance
verdict or authority decision. A formula citation does not establish project
applicability.

This PR does not change project schema 24, compatibility policy, confinement,
component-mapped bridge checks, crack acceptance behavior, portable packaging,
signing or release identity. The runtime version remains 0.92; PR-09 owns the
final version and Windows-resource transition to 0.93.
