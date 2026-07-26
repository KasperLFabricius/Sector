# Section geometry topology policy

Sector validates polygon topology before a section can enter calculation. The
same validator is used by the Python `Section` API, Streamlit input assembly,
project save/load, raw shear/torsion helpers, and solver entry points. Solver
entry points validate again because `Section.concrete` remains mutable for
backward compatibility.

## Valid section boundary

A section has one outer ring and zero or more hole rings. Every ring must:

- be a numeric `(N, 2)` coordinate sequence with at least three distinct points;
- contain only finite coordinates;
- have a signed-area magnitude greater than the resolved area tolerance;
- be simple, with no non-adjacent edge crossing, contact, or overlap;
- contain no repeated or tolerance-coincident vertices; and
- contain no adjacent edge pair that reverses over the same line.

Intentional intermediate collinear points are valid when the boundary continues
in the same direction. One final point exactly equal to the first is also valid
as a conventional serialization closure marker. It is ignored for topology
classification, but the caller's raw point order is preserved. A merely
near-coincident terminal point is invalid under the tolerance policy.

Every hole must be strictly inside the outer ring. A hole boundary must not
touch or cross the outer boundary. Hole boundaries must not touch, cross, or
overlap each other, and one hole must not be nested inside another.

Ring winding is not a validity condition. Clockwise and counter-clockwise input
are accepted in every combination. Raw order is retained for input identity and
point numbering; analysis copies are oriented outer-counter-clockwise and
hole-clockwise for signed integration.

## Scale-aware tolerance

All coordinates use Sector model units (metres). For all rings in one section,
let:

- `S = max(global x span, global y span)`;
- `e_L = max(1e-12 m, 1e-9 S)`; and
- `e_A = max((1e-12 m)^2, e_L max(S, e_L))`.

Distances at or below `e_L` classify vertices or non-adjacent boundaries as
coincident/contacting and therefore invalid. Ring area magnitude must be
strictly greater than `e_A`. The validator never snaps or changes engineering
coordinates. Translation and representative scale tests bracket each limit
from both sides.

## Diagnostics and compatibility

Validation stops at the first causal defect and returns a stable issue code plus
the one-based ring, point, and/or edge location. Boundary-contact diagnostics
also report the measured clearance and resolved tolerance.

Project format version 14 is unchanged. Mixed-winding projects and exactly
closed rings continue to round-trip without reordering. A legacy representation
that concatenates multiple independently closed rings into one self-touching
ring is invalid; callers must represent interior rings through the existing
`holes` field.
