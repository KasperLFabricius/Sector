# Sector 0.96.6: section stress and strain maps

## Purpose and scope

Show how longitudinal strain and normal stress vary across each calculated
section. Use the same retained result and figure factory in Streamlit, reports
and the manual. Keep the production solvers and project schema unchanged.

## Changes

1. Add a shared result adapter. Read accepted elastic and plastic planes,
   material laws, geometry and discrete reinforcement results. Reject missing,
   inconsistent, non-finite or unconverged evidence before drawing a map.
2. Define strain explicitly. Elastic TOTAL shows compatible section strain,
   including retained long-term deformation. Tendon material strain includes
   initial strain. Explain the distinction from recoverable concrete strain.
   Plastic maps show the selected ultimate-capacity state.
3. Draw aligned strain and stress maps with equal geometry and axes. Clip the
   display bands to the concrete outline and retain all voids. Use circles for
   bars and diamonds for tendons. Identify slab-density integration points.
4. Use tension-positive values, explicit units, a visible zero reference and
   separate concrete and reinforcement stress scales. Provide exact extrema
   and reinforcement values for static reading. Explain locally scaled maps.
5. Place the maps beside the selected Plastic state and Elastic response in
   Streamlit. Preserve the existing result tables and diagnostic profiles.
6. Add the maps to the relevant Standard and Audit case sections. Use the same
   state identifiers, signs, quantities and factory as the results view.
   Keep the Brief report focused on governing evidence.
7. Add worked maps and operating instructions to the manual. Explain scales,
   display sampling, creep, prestress, capacity-state selection and unavailable
   results. Review nearby text and cross-references for consistency.
8. Set version 0.96.6. Prepare release notes and a matching portable executable,
   PDF manual and offline HTML after all release gates pass.

## Acceptance and review sequence

Use independent numerical and figure reviews before the full CLI/CI run.
Cover uniaxial and biaxial states, uniform and zero fields, tension and
compression, concave outlines, holes, multiple material laws, prestress,
creep, invalid evidence and slab-density reinforcement. Check the plotted
values against retained solver states and independent arithmetic.

Run focused tests and render representative figures, Streamlit views and
report/manual pages. Resolve each adversarial finding and repeat review until
there are no remaining findings. Then freeze the exact candidate and run the
full required CLI/CI gates. Any correction receives a further review.

After successful review and CI, verify the merged tree and the portable
package. Test executable startup and figure export. Publish only matching
release assets and verify the public download hashes.

## Following PR

After version 0.96.6 is complete, investigate all report profiles and prepare
a detailed plan to bring their quality, presentation and readability to the
manual's standard. The current release adds the field figures and their
necessary explanations. The broader report overhaul belongs to the next PR.
