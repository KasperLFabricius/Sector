# Sector 0.97.0 notes

Sector 0.97.0 corrects calculation results that the review of 2 November 2026
found. Results of existing projects can change. A project from Sector 0.96 or
earlier loads with the corrected methods, and the load message lists them.
Project files use schema 28.

## Bending and axial force

- **Pivot C (EN 1992-1-1 6.1(5), Figure 6.1).** When the whole section is in
  compression, the strain at (1 - eps_c2/eps_cu2) h from the more compressed
  face is limited to eps_c2. The squash load and the upper part of the N-M and
  M-M envelopes decrease. Example: 400 x 400 mm, C30, 1 % B550, gamma_s = 1.20:
  3950.3 kN (was 4043.7 kN). The limit is on for the Eurocode presets. The
  concrete panel has an option to clear it for a legacy calculation.
- **N-M diagrams (TA-08).** Each diagram holds the moment about the other axis
  at the case value. On a section that is not symmetric about the bending axis,
  the diagram no longer overstates the uniaxial capacity.

## Shear chords

- **2005 family, 6.2.3(7).** The shear term on the tension chord is limited only
  by the member maximum moment MEd,max when you enter it (shared M-V-T settings,
  per bending direction and sign). Sector no longer uses the section resistance
  MRd as that limit, because with that limit the check could not fail. A button
  copies the largest case moments; this is valid only when the cases include the
  section with the maximum moment.
- **DS/EN 1992-1-1:2023, Formulae (8.51) and (8.52).** Each chord receives
  (NVd + NEd)/2, with NEd positive in tension. Example: MEd = 90 kNm,
  MRd = 100 kNm, NVd = 250 kN, z = 0.5 m gives utilisation 1.525 (was 2.15).
- **No shear reinforcement (6.2.2(5), 9.2.1.3(2); 2023 8.2.2(10)).** The tension
  chord carries MEd + |VEd| d. This is a new result in the shear view and report.
- **Bonded tendons in Asl and d (TB-05).** An option includes bonded tendons in
  the longitudinal reinforcement and the effective depth of the concrete shear
  resistance (EN 1992-2 6.2.2(101); 2023 Formula (8.36)). It is on by default for
  the 2023 edition. A section with strands only now has a shear result.
- **DK NA 6.3.2(6) sum (TB-04).** The resistance to V acting alone uses the
  installed links when they resist more than VRd,c.

## Serviceability and prestress

- **Long-term crack width (TA-03).** Formula (7.9) uses alpha_e = Es/Ecm also for
  the long-term width (7.3.4(2)). The long-term crack width increases when the
  creep coefficient is more than zero.
- **Tendon prestrain IS (TA-04).** IS is the strain difference between the tendon
  and the adjacent concrete after all losses. Under prestress alone the tendon
  stress is Ep IS. Sector adds no elastic-shortening or creep loss; it derives
  the bond strain difference, with the decompression strain, for the elastic,
  fatigue and plastic models. Prestressed sections get a higher effective
  prestress than before if IS was entered after all losses.

## Fatigue

- **Concrete fibre search (TA-01).** The damage bound separates the part of a
  box where both stress states are in compression from the part where only one
  is. The absolute tolerance is 1e-4 of the decision limit 1.0. The reference
  project now converges and gives PASS. A search that does not converge gives
  INVALID with its cause and its last bounds; the message also states the
  reinforcement verdict of the same spectrum.
- **DK NA partial factors (TA-05).** The defaults follow the selected basis:
  gamma_s,fat = 1.32 and gamma_c,fat = 1.595 for DS/EN 1992-1-1 DK NA:2024
  (2.4.2.4(1): Table 2.1Na NA values times 1.1). A note shows when the entered
  values differ. Projects keep their entered values.

## Manual and reference project

- The shear example states v_min = 0.422 MPa (MN-01). The crack-width example
  states k_t, the action duration and the short-term widths (MN-02). The status
  table lists every status that Sector shows (MN-03).
- The reference check pack uses the (n - 1) area model for compression bars,
  the DK NA fatigue factors and the converged concrete search (RP-15).

## For developers

- `AGENTS.md` gives the module map, data flow, invariants and commands.
- New calculation code is in `sector/` (no Streamlit): `capacity.concrete_route_chord`,
  `capacity.shear_tension_steel`, `elastic.bonded_prestress_stress`,
  `plastic.uniaxial_interaction`.

## Moved to a later release

- TB-06 (torsion with VEd <= VRd,c): EN 1992-1-1 6.3.2(5) and (6.31) support the
  review reading. The change affects three result validators and moves to 0.97.1.
