# Sector 0.96.6 notes

Sector 0.96.6 adds longitudinal stress and strain maps to the section results.
The maps connect concrete response with the response at each bar and tendon.
Supported project schema: 27.

## Section maps

- Plastic results show the selected ultimate-capacity state. The concrete fill
  shows values from the accepted strain plane and selected design material law.
- Elastic results offer Combined actions (TOTAL) and Sustained actions (LONG).
  Compatible strain includes the retained long-term deformation. Tendon
  material strain also includes initial strain.
- Stress maps show concrete, bars and tendons together. Different
  stress scales with material labels keep concrete and reinforcement values readable.
- Matching geometry, equal coordinate scales, void boundaries and zero lines
  with labels support comparisons. Tables give exact extrema and their
  locations. Hover labels identify individual elements and values.
- Color limits stay fixed across the valid states of the selected action.
  Other actions can use different limits. Slab-density markers identify
  integration points or nominal reinforcement axes with tributary areas.
- Calculate refreshes earlier cached results to include the retained field
  evidence required by the maps.

## Reports and manual

Standard and Audit include map pairs for each calculated Plastic and Elastic
case when figures are enabled. Plastic maps use the retained selected capacity
point. Elastic maps use TOTAL. Brief keeps its governing capacity and elastic
response figures.

The manual adds four worked maps and explains scales, signs, creep, initial
prestress strain, field selection and display bands. The elastic depth profile
and concrete-corner table identify instantaneous concrete strain separately
from TOTAL reinforcement strain.

## Portable build

Extract the complete `Sector-v0.96.6-windows-portable` ZIP and run `Sector.exe`.
Keep its `_internal` folder beside the executable. The package includes the
Python runtime. PDF figure export uses Microsoft Edge or another supported
Chromium browser. A SHA-256 sidecar accompanies the ZIP.

The production solvers and project schema keep their existing methods and
formats. The display bands evaluate an accepted field for presentation.
