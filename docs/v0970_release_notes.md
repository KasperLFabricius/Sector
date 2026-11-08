# Sector 0.97.0 notes

Sector 0.97.0 corrects calculation results that an internal review found. It
also adds the bonded tendons to the longitudinal tension reinforcement Asl and
to d of the shear resistance without shear reinforcement. The N-M diagrams now
hold the moment of the case about the other axis.
Supported project schema: 28.

## Open projects from earlier versions

Sector opens projects of schemas 25, 26 and 27 with the corrected methods, so
the results of an existing project can change. A load message lists each
change that applies to the project. Schema 28 adds three inputs. They are the
pivot C strain limit, the member moments MEd,max for the shear shift and the
tendon option of the shear check.

The prestrain IS has a new meaning (see Crack widths and prestress). Examine
the prestrain of each tendon in an earlier project, and enter IS = σpm/Ep.

## Section capacity

When the full section is in compression, the strain at (1 - εc2/εcu2) h from
the more compressed face is limited to εc2 (EN 1992-1-1:2004, 6.1(6) and
Figure 6.1). The concrete panel has the option **Concentric-compression strain
limit εc2 (pivot C)**. It is on by default for the EN 1992-1-1:2005 presets,
with and without DK NA:2024. It is off for DS/EN 1992-1-1:2023, because
8.1.1(3) limits only εcu. It is also off for the two legacy curve presets.

Example: the squash load of a 400 x 400 mm C30 section with 1 % B550
reinforcement is 3950.3 kN (was 4043.7 kN). A project file without a concrete
preset gets pivot C from the default preset, DS/EN 1992-1-1:2005 + DK NA:2024.

## Shear and torsion

The chord checks of shear have three corrections:

- Only the member moment MEd,max limits the shear shift of 6.2.3(7). Enter
  MEd,max for each bending direction and sign in the shared M-V-T settings.
  A button copies the largest case moments. This value is correct only when the
  cases include the section with the maximum moment. Without an entry, or with
  0, there is no limit. The section MRd is no longer the limit, so the chord
  check can fail.
- DS/EN 1992-1-1:2023, Formulae (8.51) and (8.52): each chord gets
  (NVd + NEd)/2, with NEd positive in tension. Example: MEd = 90 kNm,
  MRd = 100 kNm, NVd = 250 kN and z = 0.5 m give the utilisation 1.525
  (was 2.15).
- On the concrete shear route, the tension chord carries the moment
  MEd + |VEd| d (6.2.2(5) and 9.2.1.3(2), 2023: 8.2.2(10)). This also applies
  to members without links. With torsion, the chord also gets Ftd,T z/2. The
  shear view, the Results Overview and the report show this check.

The DK NA 6.3.2(6) sum uses the section with its installed links for V alone:
max(VRd,c, VRd) while VEd ≤ VRd,c, and VRd above VRd,c. VRd = min(VRd,s,
VRd,max) at the strut angle with the largest resistance. The term increases
with VEd. Example: the sum of the reference project is 2.132 (was 2.673).

The new option **Include bonded tendons in Asl and d** adds the bonded tendons
on the tension side to Asl and to the effective depth d. It applies to the
shear check without links:

- DS/EN 1992-1-1:2023: on by default (8.2.2(6)). d = (ds² As + dp² Ap)/(ds As
  + dp Ap), Formula (8.36), and ρl = (ds As + dp Ap)/(bw d²), Formula (8.37).
  For a face with tendons only, Formula (8.20) uses fpd of the tendons
  (8.2.1(4)).
- EN 1992-1-1:2005 presets, with and without DK NA:2024: off by default,
  because 6.2.2(1) uses only the tension reinforcement. EN 1992-2, 6.2.2(101),
  permits bonded prestressing steel for bridges. With the option on, d is the
  area-weighted mean of ds and dp.
- Tendons with the duct condition "Not grouted, soft-filled, or unbonded" or
  "Duct details not established" stay out of Asl and d.

With the option on, a section with strands only has a shear result (d = dp).
The shear view and the report show As at ds, Ap at dp and the rule for d.

## N-M interaction diagrams

Each N-M diagram holds the moment about the other axis at the case value, or
at 0 when the utilisation check is off. Before, each branch used one
neutral-axis direction. On a section that is not symmetric about the bending
axis, this direction also gives a moment about the other axis. The diagram
could then show too large a capacity. Sector now searches all neutral-axis
directions for the states that carry the held moment.

A branch ends where the section cannot carry the held moment. When the held
moment is close to its largest value, Sector adds 8 points in the narrow band
of axial force that can carry it. The figure marks the squash load and the
tension limit only when the diagram reaches them. A diagram takes
approximately 2 to 10 s to calculate.

## Crack widths and prestress

The crack width uses αe = Es/Ecm in Formula (7.9) (2023: Formula (9.11)) for
both load durations (7.3.4(2)). The creep modular ratio sets only the cracked
state. Long-term widths increase a little, for example from 0.530 to 0.539 mm.

IS is the tendon strain under prestress alone after all losses, IS = σpm/Ep.
Sector adds no losses. Sector derives the bond strain difference
εp(0) = IS - εc,p. The elastic and fatigue models use the modular ratio nl.
The plastic model uses Es/Ecm with the entered Ec. Its ULS prestrain includes
the decompression strain. εp(0) can be negative for a tendon with a low
stress. Ec stays editable in Plastic mode when the section has tendons.

## Fatigue

The section search for concrete fatigue has a correct upper bound, so it
converges also above approximately 10^6 cycles. Each published concrete
damage is the upper bound D,upper, and the verdict uses it. A search that does
not converge is INVALID and shows its cause and bounds.

The DK NA:2024 defaults of the fatigue partial factors are γs,fat = 1.32 and
γc,fat = 1.595 (2.4.2.4(1)). A note shows when the entered values differ from
the defaults. Projects keep their entered values.

## Manual and reference check pack

The manual gives vmin = 0.422 MPa and a crack-width example with kt and the
load duration. Its status table shows each status of the Results Overview and
the fatigue screens. The reference check pack uses the (n - 1) area model for
compression bars and the DK NA:2024 fatigue factors. Its concrete fatigue
search converges (PASS).

## Known limitations

- With torsion, when VEd ≤ VRd,c, Sector does not add a shear force to the
  links. A later release examines this rule.
- In Stage I, the locked-in tendon stress under prestress alone can differ
  from Ep IS by up to approximately 1.8 %. In the examined cases no verdict
  changed. A later release examines this state.
- Near the tension limit, an N-M branch can be narrower than the true
  capacity at some axial forces. The diagram is then on the safe side.

## Software and build

Sector uses Python 3.14.10 and Streamlit 1.66.1, with current versions of the
runtime, test and build packages. These changes do not change the calculation
results.

## Portable build

Extract the complete `Sector-v0.97.0-windows-portable` ZIP and run
`Sector.exe`. Keep its `_internal` folder beside the executable. The package
includes the Python runtime. PDF figure export uses Microsoft Edge or another
supported Chromium browser. A SHA-256 sidecar accompanies the ZIP. PDF and
offline HTML manuals are separate downloads.
