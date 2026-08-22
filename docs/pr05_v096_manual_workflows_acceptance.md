# PR-05 acceptance — manual workflows and end-user scope

## Frozen base and product boundary

- Base: `19af70b7966ff97eec93364fd703b4d73eb080db` (`origin/main` after PR-04).
- Decision owners: D096-010 and D096-011.
- Product version remains `0.95`; PR-05 does not change calculations, project
  persistence, report contents, packaging or release metadata.

## User-action workflow contract

Every Task workflows row must state an explicit action. Generic prose such as
"complete the shown inputs and calculate or review as applicable" is not a
route. Stage and view names below are the exact visible application labels.

| Workflow | Required route |
|---|---|
| Create a section | `Inputs > Section`; define concrete, void and reinforcement geometry; confirm the preview; calculate. |
| Define materials and reinforcement | `Inputs > Material parameters`; define material laws; use `Inputs > Section` for reinforcement assignments; calculate. |
| Enter actions | `Inputs > Loads`; enter uniquely named rows; calculate. |
| Calculate elastic response and crack width | Select Elastic and criteria under `Inputs > Analysis settings`; define the Elastic row under `Inputs > Loads`; calculate; open `Analysis > Elastic Results`. |
| Calculate plastic capacity | Select Plastic under `Inputs > Analysis settings`; define the row under `Inputs > Loads`; calculate; open `Analysis > Plastic Results` or `Analysis > N-M Interaction`. |
| Calculate grouped fatigue | Enable Fatigue under `Inputs > Analysis settings`; complete material/detail and spectrum inputs; calculate; open `Analysis > Fatigue Results`. |
| Review detailing | Enable the required checks under `Inputs > Analysis settings`; complete dependent inputs; calculate; open `Analysis > Detailing`. |
| Review results | Calculate after the final input edit; open `Analysis > Results Overview`; follow the governing row to its named detail view. |
| Save or load a project | Use `Inputs > Project`; after loading, review restored inputs and calculate before using results. |
| Choose a report profile | With current results, use `Report`; enter metadata, choose the profile, generate and download. |

Troubleshooting corrections must name the input stage or result view the user
can act on. Recalculate is required after changed or loaded calculation inputs.
Regenerate a report only when a refreshed publication is the task; it is not a
generic correction for an input or result warning.

The Results Overview warning is routed through the shared manual registry and
points to `Analysis > Results Overview` plus the row's named detail view.

## Current end-user manual contract

The issued PDF and HTML manual describe current operation and engineering
interpretation. They do not publish internal development or distribution
administration. Remove the following visible material:

- repository contract paths;
- project-schema identities or schema-version instructions;
- source-ZIP, portable-build, runtime-installation, checksum, receipt or
  unsigned-distribution procedures;
- report page targets, recorded content reasons and visual-approval policy;
- instructions to open a project in another Sector release; and
- narration comparing current behaviour with former Sector versions.

Build and packaging instructions remain in developer/distribution documents,
not in the end-user manual. Current product and source-revision metadata remain
because they identify the manual being read. The product-identity limitation
that Sector is not a certification, sign-off, approval or code-completeness
system remains user-relevant.

## Acceptance matrix

| ID | Condition | Required result |
|---|---|---|
| MW96-01 | Task workflows are inspected | Every workflow has a non-empty explicit action and uses exact visible stage/view labels. |
| MW96-02 | A workflow input is invalid | Its correction routes to the applicable `Inputs` stage, not to report regeneration. |
| MW96-03 | Results Overview retains a warning state | The Streamlit warning uses the shared `results-review` manual entry. |
| MW96-04 | A project is loaded | The manual states that inputs are restored, prior results are cleared and Calculate is required, without schema/release history. |
| MW96-05 | Report generation fails | Recalculation is prescribed only when stale or missing results are the displayed cause. |
| MW96-06 | Visible PDF and HTML manual text is scanned | Repository/schema/build/release-administration and former-version wording are absent. |
| MW96-07 | The report-profile table is read | It explains purpose and omitted detail without page-target or QA-administration columns. |
| MW96-08 | Manual publication inventories are checked | Updated table identities, content hashes, PDF outline and HTML destinations are internally consistent. |
| MW96-09 | PDF and HTML artifacts are generated | Text is extractable, pages are A4 and visually reviewed sections remain readable without orphaned workflow rows. |
| MW96-10 | Scope and version are inspected | Solver results, report calculations, project-file behaviour and product version are unchanged. |

## Verification order

1. New end-user-scope and explicit-route adversarial tests.
2. Existing manual information-architecture, manual, publication-object,
   HTML/PDF fixture and warning-routing tests.
3. Targeted compile, Ruff, diff, version and programme-document guards.
4. Real PDF/HTML generation, structural preflight and focused raster review.
