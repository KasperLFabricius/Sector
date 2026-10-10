# Sector 0.96.5 manual acceptance

Base: 4d4a5fd6f40fc03b7b4b8d6517f0e6d76057b741.
Scope: manual explanations, worked examples, figures, publication layout,
offline HTML illustrations, release metadata and portable distribution.

| Requirement | Evidence required |
| --- | --- |
| Elastic reproduction | Independent rectangular transformed-section arithmetic agrees with native stresses and compression depth. |
| Plastic reproduction | Published band and reinforcement resultants balance the named action and reproduce its moment. Band refinement values are retained. |
| Duration combination | LONG, retained component, instantaneous response, TOTAL and DIF reproduce the native combination. |
| Honest approximations | Polygon geometry, 80 midpoint bands, angular sampling, first strain limit and displaced-concrete choices are explicit. |
| Broader explanations | Crack geometry, shear truss, torsion tube, combined demands, detailing and fatigue each have a physical explanation and relevant figure. |
| Publication integrity | Existing 33 governed equations retain their identities, sources, units and dependencies. New table and figure inventories are fixed and checked. |
| Offline HTML | Every figure has an embedded image, useful alternative and caption. No script or network resource is required. |
| Visual quality | All illustrated PDF pages and new figures are inspected at reading size. Navigation, symbols, layout and image checks pass. |
| Numerical scope | Production solver modules and saved-project schema remain unchanged. |
| Distribution | Version 0.96.5, matching build metadata, portable executable startup, image export, ZIP and SHA-256 verified. |

Run independent example checks first, then manual and publication tests, then
affected application/packaging checks. Preserve existing numerical and release
checks. Record commands and results in the final release evidence.

## Validation environment corrections

Two test-harness failures were reproduced on the unchanged 0.96.4 base.
The Quick Section adapter now removes retired widget references and completes
the pending full rerun when the input-stage selector has not yet remounted.
Checks cover live controls, session-state preservation and native report routes.

The native handle-isolation test uses the underlying Python interpreter for its
standard-library worker. This avoids measuring the Windows virtual-environment
redirector's child-process lifetime. The private-handle assertions, expected
protocol output and 1.5-second limit remain in place. Both corrections affect
tests only.

The complete CI run also exposed three fatigue-test failures that reproduce on
the unchanged base. The mixed-bond arithmetic now covers both displaced-concrete
settings explicitly. The report-depth checks accept either symmetric top corner
only after verifying their raw criterion values and the narrow governing tie.
They still require one Standard row, all Audit rows and matching profile headings.
The introduced strain-notation finding uses the established U+2030 symbol in the
manual text, captions, alternatives and figure axis. Its PNG and manifest are
regenerated from the corrected source.
