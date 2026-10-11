"""Fail-closed figure and table identities for Sector publications."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Iterable


class PublicationContractError(ValueError):
    """Raised when authored publication content no longer matches its contract."""


@dataclass(frozen=True)
class PublicationItem:
    """One visible figure or table identity shared by reference and caption."""

    kind: str
    number: str
    caption: str

    def __post_init__(self) -> None:
        if self.kind not in {"Figure", "Table"}:
            raise PublicationContractError(
                f"Unsupported publication kind: {self.kind!r}."
            )
        if not self.number.strip() or not self.caption.strip():
            raise PublicationContractError(
                "Publication number and caption must both be non-empty."
            )

    @property
    def label(self) -> str:
        return f"{self.kind} {self.number}"

    @property
    def anchor(self) -> str:
        number = re.sub(r"[^a-z0-9]+", "-", self.number.lower()).strip("-")
        return f"{self.kind.lower()}-{number}"

    @property
    def caption_text(self) -> str:
        return f"{self.label}. {self.caption}"

    @property
    def continued_caption_text(self) -> str:
        return f"{self.label} (continued). {self.caption}"

    @property
    def markdown_reference(self) -> str:
        return f"[See {self.label}](#{self.anchor})."


class PublicationCounter:
    """Issue independent, section-based figure and table ordinals."""

    def __init__(self, section: str = "0", separator: str = ".") -> None:
        self._separator = separator
        self.enter_section(section)

    def enter_section(self, section: str) -> None:
        section = str(section).strip()
        if not section:
            raise PublicationContractError("A publication section is required.")
        self._section = section
        self._ordinals = {"Figure": 0, "Table": 0}

    def issue(self, kind: str, caption: str) -> PublicationItem:
        if kind not in self._ordinals:
            raise PublicationContractError(
                f"Unsupported publication kind: {kind!r}."
            )
        self._ordinals[kind] += 1
        number = f"{self._section}{self._separator}{self._ordinals[kind]}"
        return PublicationItem(kind, number, str(caption))


@dataclass(frozen=True)
class ManualFigureSpec:
    part: str
    section: str
    factory: str
    caption: str
    alternative: str


@dataclass(frozen=True)
class ManualTableSpec:
    part: str
    section: str
    headers: tuple[str, ...]
    caption: str


@dataclass(frozen=True)
class PublishedManualBlock:
    block: tuple
    item: PublicationItem | None
    alternative: str | None = None


# These identities bind captions to the authored object, not merely to an index.
# A same-cardinality reorder therefore fails before any incorrect caption is shown.
MANUAL_FIGURE_SPECS = (
    ManualFigureSpec(part='Part A - Get started', section='Quick start', factory='fig_workspace_overview', caption='Workspace overview (schematic): prepare inputs, calculate and examine named results, then publish.', alternative='Three linked panels show the workspaces. Inputs has a stage selector. Analysis has Calculate and result details. Report has document details, references, profile selection and PDF generation.'),
    ManualFigureSpec(part='Part A - Get started', section='The worked examples', factory='fig_beam_section', caption='Rectangular beam: 3 x 25 mm bottom, 2 x 16 mm top.', alternative='A 300 by 600 mm concrete rectangle with three bottom bars and two top bars arranged symmetrically about the vertical centerline.'),
    ManualFigureSpec(part='Part A - Get started', section='The worked examples', factory='fig_circular_section', caption='Circular hollow section: a central void, a mild-bar ring and a tendon ring.', alternative='An annular concrete section with concentric outer and void boundaries. Mild reinforcement and prestressing tendons form two circular rings.'),
    ManualFigureSpec(part='Part B - Features & options', section='Defining the section', factory='fig_slab_spacing_cover', caption='Nominal bars in a one-meter strip with an interleaved series. Each series has its own row. The dashed outer lines mark strip cuts. Short dotted lines mark tributary boundaries. Each boundary bar has a 16 mm diameter and half-area weight. The two cover details use the same scale and full physical bar diameters.', alternative='The 20 mm bar row has five axes at 200 mm spacing. The 16 mm bar row has six axes offset by 100 mm, with a half-area axis at each strip cut. Below, equal-scale details compare 20 mm edge cover with 30 mm center cover for the two bar sizes.'),
    ManualFigureSpec(part='Part B - Features & options', section='Materials', factory='fig_beam_concrete_law', caption='The concrete-law preview for the rectangular example (C40/50).', alternative='A compression stress-strain curve that increases parabolically from zero to the design strength and then stays horizontal to the ultimate strain.'),
    ManualFigureSpec(part='Part B - Features & options', section='Materials', factory='fig_beam_steel_law', caption='The B550 mild-steel law for the rectangular example.', alternative='A symmetric reinforcing-steel stress-strain curve with linear tension and compression branches to yield followed by the selected post-yield response.'),
    ManualFigureSpec(part='Part B - Features & options', section='Materials', factory='fig_circular_prestress_law', caption='The tendon law for the circular example.', alternative='A prestressing-steel stress-strain curve with an initial elastic branch and a nonlinear branch to design strength and ultimate strain.'),
    ManualFigureSpec(part='Part B - Features & options', section='Analysis & result settings', factory='fig_beam_envelope', caption="The rectangular example's biaxial envelope with the applied load. The sweep from 0 to 360 degrees closes the curve.", alternative='A closed $M_x$-$M_y$ capacity boundary around the origin with one applied-load point. Each boundary vertex is the result for one neutral-axis orientation.'),
    ManualFigureSpec(part='Part B - Features & options', section='Analysis & result settings', factory='fig_directional_shear_faces', caption='Directional shear geometry for a 300 by 600 mm rectangle with positive adjusted bending moments. Filled circles identify the selected longitudinal bars. The vertical shear uses the bottom bars and a 550 mm effective depth. The horizontal shear uses the left bars and a 250 mm effective depth.', alternative='Two equal-scale section views pair vertical shear with bending about the x axis and horizontal shear with bending about the y axis. The first view measures effective depth from the top compression edge to the bottom bar centers. The second measures it from the right compression edge to the left bar centers. The selected web widths are 300 and 600 mm.'),
    ManualFigureSpec(part='Part B - Features & options', section='Analysis & result settings', factory='fig_torsion_partition', caption='Positioned rectangles for a full T-section partition. The web and flange meet at $y=100$ mm. Their interiors have no overlap, and their areas sum to $200000\\,\\text{mm}^{2}$. Crosses mark the rectangle centers. Rectangle 1 is the web paired with shear.', alternative='The T-section has a 200 by 400 mm web and a 600 by 200 mm flange. The web center is (0, -100) mm. The flange center is (0, 200) mm. An adjacent table gives the four inputs for each rectangle.'),
    ManualFigureSpec(part='Part B - Features & options', section='Reading the results', factory='fig_plastic_strain_map', caption='Circular example at ultimate capacity: axial compression 1500 kN and neutral-axis angle 45 degrees. Tendon material strain includes initial strain.', alternative='The annular section has a diagonal compatible strain field. Bar circles and tendon diamonds use the same strain scale. The central void stays empty.'),
    ManualFigureSpec(part='Part B - Features & options', section='Reading the results', factory='fig_plastic_stress_map', caption='Stress in the same ultimate-capacity state. Concrete and reinforcement use different stress scales with material labels.', alternative='Concrete compression occupies one side of the annulus. Discrete bar and tendon markers show the calculated material stresses. The void remains empty.'),
    ManualFigureSpec(part='Part B - Features & options', section='Reading the results', factory='fig_elastic_strain_map', caption='Rectangular example: TOTAL compatible strain for sustained moment 100 kNm, additional moment 50 kNm, concrete modulus 35 GPa and creep coefficient 2. Axial force is zero.', alternative='A vertical compatible strain gradient crosses the rectangular section. The bar strains lie on that plane. A dashed line marks zero section strain.'),
    ManualFigureSpec(part='Part B - Features & options', section='Reading the results', factory='fig_elastic_stress_map', caption='Stress for the same combined actions. Concrete compression uses the instantaneous stress plane. Bar stress includes retained long-term stress.', alternative='Concrete stress is zero in the tensile region and becomes compressive toward the top. Bar circles show their total stresses on the reinforcement scale.'),
    ManualFigureSpec(part='Part C - Theory & methodology', section='Conventions and sign convention', factory='fig_sign_convention', caption='Axes and the positive senses of the axial force, the moments and the neutral-axis angle.', alternative='The x-axis points right, and the y-axis points up. Arrows show positive axial force and moments. The neutral-axis angle is measured from positive y.'),
    ManualFigureSpec(part='Part C - Theory & methodology', section='Conventions and sign convention', factory='fig_discretization', caption='Three distinct approximations: polygon geometry, plastic stress bands, and capacity orientations. Geometry is schematic.', alternative='An annular polygon with discrete reinforcement, a rectangle divided into stress bands, and sampled line orientations distinguish the three numerical choices.'),
    ManualFigureSpec(part='Part C - Theory & methodology', section='Material laws', factory='fig_beam_concrete_law', caption='The C40/50 parabola-rectangle law of the beam example.', alternative='Concrete compression stress increases on a curved branch to its design plateau, which continues until the marked crushing strain.'),
    ManualFigureSpec(part='Part C - Theory & methodology', section='Material laws', factory='fig_beam_steel_law', caption='The B550 mild-steel law of the beam example.', alternative='Positive and negative B550 stress branches are linear to the yield points and then follow matching post-yield branches to the strain limits.'),
    ManualFigureSpec(part='Part C - Theory & methodology', section='Material laws', factory='fig_circular_prestress_law', caption='The tendon law of the circular example.', alternative='The tendon curve starts with an elastic slope, curves in the direction of the proof-strength region and ends at the defined ultimate strain.'),
    ManualFigureSpec(part='Part C - Theory & methodology', section='Cracked-section elastic analysis', factory='fig_beam_cracked', caption="The beam's cracked (Stage II) state under the service moment: the compression zone (shaded) above the neutral axis.", alternative='A rectangular section has a shaded concrete compression zone above a horizontal neutral axis, with reinforcement points included in the Stage II section.'),
    ManualFigureSpec(part='Part C - Theory & methodology', section='Cracked-section elastic analysis', factory='fig_elastic_fields', caption='Rectangular elastic example: geometry, concrete stress and reinforcement stresses share the depth scale. Section width is exaggerated. Tension is positive.', alternative='The compression zone ends 149.251 mm below the top. Concrete has a triangular compression stress distribution. Top steel is in compression, and bottom steel is in tension.'),
    ManualFigureSpec(part='Part C - Theory & methodology', section='Cracked-section elastic analysis', factory='fig_elastic_balance', caption='The neutral-axis equation crosses zero at the balanced compression depth. The curve evaluates the equation at a range of trial depths.', alternative='The signed transformed first moment changes from negative to positive and crosses zero at compression depth 149.251 mm.'),
    ManualFigureSpec(part='Part C - Theory & methodology', section='Cracked-section elastic analysis', factory='fig_duration_components', caption='Bottom-bar stress components for the sustained-plus-additional example. TOTAL equals the retained component plus RST1.', alternative='Five columns compare the stress components LONG, retained stress, RST1, TOTAL and DIF for the same bottom reinforcement element and one specified action history.'),
    ManualFigureSpec(part='Part C - Theory & methodology', section='Plastic capacity analysis', factory='fig_strain_plane', caption='The capacity strain plane uses the reported tension-positive convention. The straight line is zero at the neutral axis, with compression above and tension below it. In this concrete-governed example, the top fiber reaches the crushing strain. The calculation formula above is compression-positive. The reported strains negate it.', alternative='A straight strain line crosses zero at the neutral axis. Negative compression lies above it, and positive tension lies below it. The top fiber reaches ultimate concrete compression.'),
    ManualFigureSpec(part='Part C - Theory & methodology', section='Plastic capacity analysis', factory='fig_beam_envelope', caption='The beam envelope with its applied load. Each vertex is one solved neutral-axis angle.', alternative='A closed biaxial moment-resistance curve contains the design moment point. Discrete points identify the angular sweep.'),
    ManualFigureSpec(part='Part C - Theory & methodology', section='Plastic capacity analysis', factory='fig_capacity_limits', caption='Strain-limit comparison example. The right panel assumes a tensile steel limit of 10 \u2030. It represents a different material from the worked beam.', alternative='Two compatible straight strain lines show different governing limits. One reaches 3.5 \u2030 concrete compression. The other reaches its assigned steel tension limit before concrete crushing.'),
    ManualFigureSpec(part='Part C - Theory & methodology', section='Plastic capacity analysis', factory='fig_plastic_bands', caption='Worked plastic compression zone, with depth exaggerated for band visibility. Each displayed group contains ten integration bands. The plateau has its own integral.', alternative='The top part has constant design compression stress. The lower part follows the rising law down to zero stress at the neutral axis.'),
    ManualFigureSpec(part='Part C - Theory & methodology', section='Plastic capacity analysis', factory='fig_envelope_ray', caption='A fixed-N envelope from 15-degree orientation steps. The applied biaxial moment lies on a ray from the origin to the boundary.', alternative='Discrete capacity points define a closed moment polygon. A ray through the applied pair $M_x$ = 180 kNm and $M_y$ = 30 kNm intersects that polygon to define utilization.'),
    ManualFigureSpec(part='Part C - Theory & methodology', section='Plastic capacity analysis', factory='fig_nm_interaction', caption='Rectangular beam: axial-force sweeps at 90 and 270 degrees. Each branch has 33 calculated points. Axial tension is positive.', alternative='The two fixed-orientation branches span tensile and compressive axial forces. The positive-bending branch crosses zero axial force at 345.98 kNm.'),
    ManualFigureSpec(part='Part C - Theory & methodology', section='Serviceability: cracking and crack width', factory='fig_crack_geometry', caption='Effective tension areas for the four worked method/system results. All panels share the depth scale. Section widths are compressed for comparison.', alternative='Four aligned rectangles share the bottom tension face. Effective heights are 125 mm for EN 2005, 125 mm for DK fine, 100 mm for DK coarse and 175 mm for EN 2023.'),
    ManualFigureSpec(part='Part C - Theory & methodology', section='Grouped fatigue', factory='fig_fatigue_sn', caption='Two-slope characteristic and design S-N curves. Each labeled marker is one applied spectrum bin. The two axes use logarithmic scales.', alternative='A log-log stress-range versus cycles plot shows characteristic and design S-N curves with a knee. The applied spectrum-bin points are below the design resistance curve.'),
    ManualFigureSpec(part='Part C - Theory & methodology', section='Grouped fatigue', factory='fig_fatigue_damage', caption='Per-bin and cumulative Miner damage for the same element. The cumulative line and $D=1.00$ limit show the governing contribution and remaining margin. The y-axis changes to a logarithmic scale for low-damage spectra so small contributions stay readable.', alternative='Damage bars identify each spectrum bin, a cumulative Miner-damage line increases across the bins, and a horizontal D equals 1 limit shows the remaining margin.'),
    ManualFigureSpec(part='Part C - Theory & methodology', section='Grouped fatigue', factory='fig_fatigue_actions', caption='Fatigue action example: a 100 kNm basic moment and a repeated additional 50 kNm. Enter the cycle count in its field.', alternative='Repeated moment peaks increase from a sustained 100 kNm baseline to 150 kNm. The vertical increment is the cyclic action component.'),
    ManualFigureSpec(part='Part C - Theory & methodology', section='Shear resistance', factory='fig_shear_truss', caption='Shear truss and resistance trade-off. Curves use the rounded values of the C35 linked-beam example. The force-path sketch is schematic.', alternative='Inclined concrete struts transfer load between the chords while vertical links carry tension. Link resistance increases with cotangent theta and concrete crushing resistance falls over the plotted range.'),
    ManualFigureSpec(part='Part C - Theory & methodology', section='Torsion (thin-walled tube)', factory='fig_torsion_tube', caption='Effective tube for the 300 x 600 mm torsion example. The dashed centerline is 50 mm inside the concrete boundary.', alternative='The outer rectangle encloses a dashed 200 by 500 mm tube centerline. Arrows circulate around that line. Its enclosed area is 100000 $\\text{mm}^{2}$ and its perimeter is 1400 mm.'),
    ManualFigureSpec(part='Part C - Theory & methodology', section='Combined M-V-T interaction', factory='fig_combined_paths', caption='Schematic force paths for concurrent longitudinal and transverse demands.', alternative='All four chord faces surround the section. A closed stirrup carries the sum of applicable shear and torsion demands at one common strut angle.'),
    ManualFigureSpec(part='Part D - Numerical procedures', section='Polygon clipping and area integrals', factory='fig_polygon_clipping', caption='Polygon clipping example. Coordinates are in millimeters. The plane is $q=0.24+0.0002x-0.001y$ MPa. Retain $q\\le0$. Subtract the clipped void. Edge a-b intersects the boundary at c.', alternative='The left panel shows the retained outer polygon and the clipped void. The right panel gives $q_a=0.32$ MPa and $q_b=-0.28$ MPa. The crossing fraction is $8/15$, and point c is at (400, 320) mm.'),
    ManualFigureSpec(part='Part D - Numerical procedures', section='Biaxial section with a void and tendon', factory='fig_elastic_iteration', caption='Elastic iteration for the biaxial example. Shading shows compressed concrete. The dashed line is the neutral axis. Circles identify bars. The diamond identifies the tendon.', alternative='Equal-scale section views show the first and accepted compression zones around the void. Circles identify bars and a diamond identifies the tendon.'),
    ManualFigureSpec(part='Part D - Numerical procedures', section='Plastic depth search and force integration', factory='fig_plastic_bisection', caption='Plastic depth search for the rectangular example at zero axial force. Diamonds mark the first six evaluated midpoints. Each interval contains the accepted depth $c=83.799$ mm. The axial sum uses the compression-positive calculation convention.', alternative='Two aligned plots show axial residual against compression depth and the depth interval before each of the first six bisection trials. The accepted root is 83.799 mm. The trial depths are 300, 150, 75, 112.5, 93.75 and 84.375 mm.'),
    ManualFigureSpec(part='Part D - Numerical procedures', section='Sustained actions and locked prestress', factory='fig_duration_sequence', caption='Duration calculation sequence for a reinforced or prestressed section. C includes the sustained actions and additional actions. Element stress is tension-positive. Each solve uses the net transformed section.', alternative='Four steps show sustained equilibrium and the adjusted instantaneous solve. A branch from sustained equilibrium gives LONG. The instantaneous solve supplies TOTAL. LONG and TOTAL connect to DIF.'),
)


MANUAL_TABLE_SPECS = (
    ManualTableSpec(part='Part A - Get started', section='Introduction & purpose', headers=('Calculation', 'Purpose and principal output', 'Read next'), caption='Available calculations and reading routes'),
    ManualTableSpec(part='Part A - Get started', section='Introduction & purpose', headers=('Capability', '2005 base', '2005 + DK NA:2024', '2023'), caption='Implemented capabilities by design basis'),
    ManualTableSpec(part='Part A - Get started', section='Start here', headers=('Reading path', 'Use it when', 'Destination'), caption='Manual reading paths'),
    ManualTableSpec(part='Part A - Get started', section='Quick start', headers=('Material input', 'Value entered in Sector', 'Use'), caption='Tutorial material inputs'),
    ManualTableSpec(part='Part A - Get started', section='Quick start', headers=('Corner', '$x$ (mm)', '$y$ (mm)'), caption='Tutorial concrete corner coordinates'),
    ManualTableSpec(part='Part A - Get started', section='Quick start', headers=('Bar', '$x$ (mm)', '$y$ (mm)', 'Diameter (mm)'), caption='Tutorial bar coordinates and diameters'),
    ManualTableSpec(part='Part A - Get started', section='Quick start', headers=('Table and case name', 'Entered actions', 'Requested output'), caption='Tutorial action rows'),
    ManualTableSpec(part='Part A - Get started', section='Quick start', headers=('Result', 'Expected value', 'Comparison tolerance'), caption='Tutorial expected results and comparison tolerances'),
    ManualTableSpec(part='Part A - Get started', section='Task workflows', headers=('Task', 'Outcome'), caption='Task index and intended outcomes'),
    ManualTableSpec(part='Part A - Get started', section='The worked examples', headers=('Named variant / calculation', 'Section and materials', 'Actions / changed assumptions'), caption='Named worked examples and changed assumptions'),
    ManualTableSpec(part='Part B - Features & options', section='Input reference', headers=('Application stage', 'Manual destination'), caption='Application input stages and manual destinations'),
    ManualTableSpec(part='Part B - Features & options', section='The workspace', headers=('View', 'Shows'), caption='Analysis result views and their reported information'),
    ManualTableSpec(part='Part B - Features & options', section='Defining the section', headers=('Size basis', 'Entered', 'Calculated'), caption='Reinforcement size input bases'),
    ManualTableSpec(part='Part B - Features & options', section='Defining the section', headers=('Shape', 'Produces'), caption='Quick Section builder shapes'),
    ManualTableSpec(part='Part B - Features & options', section='Defining the section', headers=('Field / unit', 'Meaning / sign', 'Default / validation'), caption='Concrete corner points - field reference'),
    ManualTableSpec(part='Part B - Features & options', section='Defining the section', headers=('Field / unit', 'Meaning / sign', 'Default / validation'), caption='Concrete void points - field reference'),
    ManualTableSpec(part='Part B - Features & options', section='Defining the section', headers=('Field / unit', 'Meaning / sign', 'Default / validation'), caption='Reinforcing bars - field reference'),
    ManualTableSpec(part='Part B - Features & options', section='Defining the section', headers=('Field / unit', 'Meaning / sign', 'Default / validation'), caption='Prestressing tendons - field reference'),
    ManualTableSpec(part='Part B - Features & options', section='Analysis & result settings', headers=('Section cut', 'Modelled reinforcement direction'), caption='Section cuts and modeled reinforcement directions'),
    ManualTableSpec(part='Part B - Features & options', section='Analysis & result settings', headers=('Member', 'Vertical shear-link spacing limits'), caption='Vertical shear-link spacing limits'),
    ManualTableSpec(part='Part B - Features & options', section='Analysis & result settings', headers=('Edition', 'Minimum-reinforcement method'), caption='Minimum-reinforcement methods by edition'),
    ManualTableSpec(part='Part B - Features & options', section='Analysis & result settings', headers=('Crack-width design basis', 'What it changes'), caption='Crack-width method differences'),
    ManualTableSpec(part='Part B - Features & options', section='Analysis & result settings', headers=('Input', 'Use'), caption='Grouped-fatigue input fields'),
    ManualTableSpec(part='Part B - Features & options', section='Analysis & result settings', headers=('Fatigue edition', 'Implemented resistance basis'), caption='Fatigue resistance bases by edition'),
    ManualTableSpec(part='Part B - Features & options', section='Analysis & result settings', headers=('Component', 'Geometry and related bending'), caption='Shear components and related bending'),
    ManualTableSpec(part='Part B - Features & options', section='Analysis & result settings', headers=('Shear method', 'What it sets'), caption='Implemented shear methods'),
    ManualTableSpec(part='Part B - Features & options', section='Loads', headers=('Table', 'Per-row fields', 'Row-specific rule'), caption='Action tables, row fields and row-specific rules'),
    ManualTableSpec(part='Part B - Features & options', section='Loads', headers=('Field / unit', 'Meaning / sign', 'Default / validation'), caption='Plastic and capacity cases - field reference'),
    ManualTableSpec(part='Part B - Features & options', section='Loads', headers=('Field / unit', 'Meaning / sign', 'Default / validation'), caption='Elastic cases - field reference'),
    ManualTableSpec(part='Part B - Features & options', section='Loads', headers=('Field / unit', 'Meaning / sign', 'Default / validation'), caption='Grouped fatigue spectrum - field reference'),
    ManualTableSpec(part='Part B - Features & options', section='Reading the results', headers=('Status', 'Meaning', 'Next action'), caption='Result status meanings and next actions'),
    ManualTableSpec(part='Part B - Features & options', section='Reading the results', headers=('Profile', 'Purpose', 'Not included'), caption='Report profiles and presentation depth'),
    ManualTableSpec(part='Part C - Theory & methodology', section='Method reference', headers=('Engineering task', 'Method destination'), caption='Engineering method reference destinations'),
    ManualTableSpec(part='Part C - Theory & methodology', section='Cracked-section elastic analysis', headers=('Input', 'Value', 'Meaning'), caption='Cracked-section elastic analysis - input and calculation values'),
    ManualTableSpec(part='Part C - Theory & methodology', section='Cracked-section elastic analysis', headers=('Result', 'Independent calculation', 'Sector calculation'), caption='Rectangular elastic example: independent and Sector results'),
    ManualTableSpec(part='Part C - Theory & methodology', section='Cracked-section elastic analysis', headers=('Equilibrium row', 'Coefficients of ($q_0$, $g_x$, $g_y$)', 'Tension-positive internal target'), caption='Elastic equilibrium matrix and signed targets'),
    ManualTableSpec(part='Part C - Theory & methodology', section='Cracked-section elastic analysis', headers=('Bottom-bar quantity', 'Calculation', 'Stress (MPa)'), caption='Cracked-section elastic analysis - bottom-bar quantity and calculation values'),
    ManualTableSpec(part='Part C - Theory & methodology', section='Plastic capacity analysis', headers=('Input', 'Value', 'Meaning'), caption='Plastic capacity analysis - input and calculation values'),
    ManualTableSpec(part='Part C - Theory & methodology', section='Plastic capacity analysis', headers=('Concrete region', 'Area ($\\text{mm}^{2}$)', 'Force (kN)', '$M_x$ (kNm)'), caption='Plastic concrete regions, areas, forces and moments'),
    ManualTableSpec(part='Part C - Theory & methodology', section='Plastic capacity analysis', headers=('Contribution', 'Force (kN)', '$M_x$ (kNm)'), caption='Plastic equilibrium force and moment contributions'),
    ManualTableSpec(part='Part C - Theory & methodology', section='Plastic capacity analysis', headers=('Rising-region bands', 'Beam resistance $M_x$ (kNm)'), caption='Concrete band-refinement comparison'),
    ManualTableSpec(part='Part C - Theory & methodology', section='Serviceability: cracking and crack width', headers=('Crack-width edition', 'Crack spacing (mm)', '$h_{c,ef}$ (m)', '$w_k$ (mm)'), caption='Worked crack-width comparison by edition'),
    ManualTableSpec(part='Part C - Theory & methodology', section='Grouped fatigue', headers=('Fatigue basis and named detail', 'Simplified limit'), caption='Stress-range limits for simplified fatigue checks of reinforcement'),
    ManualTableSpec(part='Part C - Theory & methodology', section='Grouped fatigue', headers=('Edition', 'Reinforcement', 'Concrete', 'Mixed bond'), caption='Fatigue editions, reinforcement scope and concrete scope'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Calculation conventions', headers=('Quantity', 'Application entry', 'Numerical value'), caption='Application units and worksheet conversions'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Evaluate the plastic material laws', headers=('Curve 1 contribution', 'Compression stress magnitude (MPa)'), caption='Concrete Curve 1 polynomial terms'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Evaluate the plastic material laws', headers=('Tension point', 'Strain', 'Stress'), caption='Tensile branch endpoints for the general steel law'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Evaluate the plastic material laws', headers=('Curve', 'Strain interval (%)', 'Characteristic stress (MPa)'), caption='Fixed tendon-law stress expressions'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Polygon clipping and area integrals', headers=('Integral', 'Contribution from each edge', 'Unit'), caption='Signed polygon contributions from each edge'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Elastic equilibrium procedure', headers=('Row', '$q_0$ coefficient', '$g_x$ coefficient', '$g_y$ coefficient'), caption='Concrete equilibrium matrix'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Biaxial section with a void and tendon', headers=('Ring', 'Ordered coordinates (mm)'), caption='Concrete and void coordinates for the biaxial example'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Biaxial section with a void and tendon', headers=('Element', '$x$ (mm)', '$y$ (mm)', 'Area or diameter', 'Modulus / initial strain'), caption='Reinforcement properties for the biaxial example'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Biaxial section with a void and tendon', headers=('Initial matrix row', '$q_0$ coefficient', '$g_x$ coefficient', '$g_y$ coefficient'), caption='Uncracked initial equilibrium matrix'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Biaxial section with a void and tendon', headers=('First clipped matrix row', '$q_0$ coefficient', '$g_x$ coefficient', '$g_y$ coefficient'), caption='First clipped equilibrium matrix'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Biaxial section with a void and tendon', headers=('First evaluation', 'Component 1', 'Component 2', 'Component 3'), caption='First equilibrium evaluation and Newton correction'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Biaxial section with a void and tendon', headers=('Clipped ring at first evaluation', 'Ordered coordinates (m)'), caption='First clipped polygon coordinates'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Biaxial section with a void and tendon', headers=('Net concrete integral', 'First evaluation value'), caption='First clipped concrete area integrals'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Biaxial section with a void and tendon', headers=('Evaluation', '$q_0$', '$g_x$', '$g_y$'), caption='Plane coefficients during elastic iteration'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Biaxial section with a void and tendon', headers=('Evaluation', '$r_N$ (kN)', '$r_y$ (kNm)', '$r_x$ (kNm)'), caption='Elastic iteration equilibrium residuals'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Biaxial section with a void and tendon', headers=('Element', 'Passive stress (MPa)', 'Locked stress (MPa)', 'Reported stress (MPa)'), caption='Accepted reinforcement stresses in the biaxial example'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Plastic depth search and force integration', headers=('Step', 'Lower $c$ (mm)', 'Upper $c$ (mm)', 'Trial $c$ (mm)'), caption='Plastic bisection depth intervals'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Plastic depth search and force integration', headers=('Step', 'Limit', '$\\kappa$ (1/m)', 'Axial residual (kN)'), caption='Plastic trial strain limits and axial residuals'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Plastic depth search and force integration', headers=('Band 1 operand', 'Value'), caption='First concrete band arithmetic'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Plastic depth search and force integration', headers=('Band 40 operand', 'Value'), caption='Fortieth concrete band arithmetic'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Plastic depth search and force integration', headers=('Band 80 operand', 'Value'), caption='Eightieth concrete band arithmetic'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Plastic depth search and force integration', headers=('Plateau operand', 'Value'), caption='Constant-stress plateau arithmetic'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Plastic depth search and force integration', headers=('Bar', 'Strain (compression +)', 'Stress (MPa)', 'Force (kN)', '$M_x$ (kNm)'), caption='Accepted bar strains, stresses, forces and moments'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Sustained actions and locked prestress', headers=('Element', 'Passive LONG (MPa)', 'Retained (MPa)'), caption='Passive sustained and retained reinforcement stresses'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Sustained actions and locked prestress', headers=('Element', 'Retained force (kN)', 'Moment using $y$ (kNm)', 'Moment using $x$ (kNm)'), caption='Retained reinforcement forces and moments'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Sustained actions and locked prestress', headers=('Target or resultant', 'Axial (kN)', 'Moment using y (kNm)', 'Moment using x (kNm)'), caption='Adjusted duration targets and retained resultants'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Sustained actions and locked prestress', headers=('Element', 'LONG (MPa)', 'RST1 (MPa)', 'Locked (MPa)', 'TOTAL (MPa)', 'DIF (MPa)'), caption='Full reinforcement stresses by duration state'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Sustained actions and locked prestress', headers=('Solve', '$q_0$', '$g_x$', '$g_y$', 'Neutral-axis equation'), caption='Sustained and instantaneous stress planes'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Construct capacity diagrams', headers=('Quantity', 'Calculation', 'Acceptance'), caption='Demand-ray intersection with a capacity segment'),
    ManualTableSpec(part='Part D - Numerical procedures', section='Construct capacity diagrams', headers=('Endpoint probe', 'Compression-positive target (kN)', 'Endpoint kept'), caption='Axial endpoint probes for the N-M diagram'),
    ManualTableSpec(part='Part E - Reference', section='Standards', headers=('Topic', 'Reference'), caption='Standards and reference sources'),
    ManualTableSpec(part='Part E - Reference', section='Limitations & troubleshooting', headers=('Symptom', 'Likely cause', 'Correction'), caption='Troubleshooting symptoms, causes and corrections'),
    ManualTableSpec(part='Part E - Reference', section='Glossary', headers=('Symbol / term', 'Meaning'), caption='Glossary of symbols and terms'),
)


# SHA-256 of each exact ordered ``(headers, rows)`` payload on the accepted
# base. Headers keep the contract reviewable; the digest also rejects a
# same-header replacement or row reorder that would otherwise look identical.
MANUAL_TABLE_CONTENT_SHA256 = (
    '6b20c184adaa4b651658778a53ff8183ca803f1070fa0b3cd33628af9121ed61',
    'c2483672f3888f6532d2eb08ea6ad4b1080d2cb5f17b8c0081d15aa387b38180',
    'ed094609ecf0cc51688848078e6522fcc58403e70902f272580f60f25af029c8',
    '4373a486391c6494e5f3a692508ced0be361454cba4736e795d5a84159817afb',
    '0223517845f9f6019dac7768823090b07a46596021ff90d6b5f5fd0b99550a9f',
    '0d7eae18417c867478757ae5c9137b618956554f64e263dde6e8622f2720d5ce',
    '349713745ccf9de9de1fd7e89cd1f91ea3708b49ac4922619f4e80a1b5d05dc3',
    'fad2f762ec2658c1b3c7c0652acbc9ec299875ce06dde54d621a529394b20195',
    '10612ff33aa10df119f3a469ea023e26fadf1a23467644b25a490f7ab25ae400',
    '8d62fef08f523f1042196737a926ebbc28e2a73e6de2f21cbaa497242fea01b9',
    'c57b1f9833250de5684b679bcfc052f15bad2be7ba78bcfbf218a880eace69a2',
    '11f87a277cb8911ebdf33e6882b6576f406f1b343aec073bb5a345ccccfa2692',
    'b972bfbfeb72f66d02898862d2af8e0ec6837629130b1fd333213cbd26ece414',
    '6ba5c8d2fe359f1dcfba739e9f53f3eacab1d645b22c07fdea93269098e8c613',
    '058bbbe1b97f1e6378d0fe2e3adf29d6054012f9760ecfc33a08e48e1b519982',
    '058bbbe1b97f1e6378d0fe2e3adf29d6054012f9760ecfc33a08e48e1b519982',
    '2d741ce574d5a44e9be3e570ee8e42987b50b12efcd88f734e120c537799e08b',
    '42e07c88e1ffeca7df360e74dd2353446b57b2bbc5ebf353710b2abe900ea884',
    'b71f3adc6e69d499e4e8eb9a96daad30c2835d64d4e8a5f88c0187608346d878',
    '722278ff88a15eaaa94f267e08dd94f7607bebd5485918fe0176f59639ef73f7',
    'a7fdb1c7ca70ba4ab7ae4253de37420e3e743587c165479ca5289db495967888',
    '7ed36e8750d774264840514550bed53f4f9dd47e2acbcd4ce41c4bc92aa991f9',
    '372920f901c164c884561b93919b1c4eca6d8751237307b3520a123236b6307d',
    '0c000a9351f557e37aa8647dc2066569d1d3477dd90b4a50a3a6726df6f59f46',
    'b71a5977c0abc6628c7e0d9b0fd539238625e559a0518d3887afd2c3be1d28e0',
    'efc492ab64b2cbe4620e319c676562ece1501b31d3cc5e7f3e0658b31485cfd4',
    'd13700878c9a9fcada6cc80fd6d34073d4684a3b9387d1d5feecbe7e8695b81e',
    '648911022eacc750dd4260968b800c124d7f5b8b769ddfa4439d59db317a283c',
    '9c3aa61c05ec8f4326ea409a087c064476be1067233ff9de70c1b245a8d0a3ad',
    'a0d214b4dcd4158ef3e0b6d2ed0a21f94cc385557aeb5eb5317ab89493ff7f2a',
    '4bebf4d227a2a9cc65f3631c871fcf0e1e3325a8fa9a9f6cbbcd3a471ecf8cab',
    '47d3d66efc6cc88b9442469869bbe4e1346a424af5ed940bfd9bf6c4677d49cd',
    '0983c6e55bb7b8362d84908e942e1917eaf516c67844767ce7a6138caf6286e5',
    'b96fa95707076988a09ba0cedf43b7bf712821727b9015b22b962fe78ad9bee8',
    '95a7b375f7ed64e412fa94357f4ec34fe02b940b6d898fd55177ca8dcc45aedb',
    '2591854b1463ae160d5ac73c21a30a5f3f4166d1a29d6d4dce394d2ecd8afe25',
    'f86e018f575238e4fb7d68cec43a98ec4f6c0d8a445b542f605724f3202aa5ee',
    'c19d00ac7913c0eef9d602c9ae1ab3285ea0f7d380f6cfce5547f2bd8988066d',
    '275e45ed2c67ca2ca29b497cc6c20b01d7e3f2c4e607eadf46eb41700a297eb6',
    '7f62573d2574d41ca9ddfbde1459b6893bb2132065829455e5a5308ae654f4a8',
    '0528c40dce8a6f8a4078f182038050cbd814d2fb49b96af16d4f8413151a8e3c',
    'df127ca9ddb602806032e01ec9fe5ba32a37171c4071c8a275b08018981bb446',
    '74ee57c418168df35355bd426c2966bb59d9222e5aee071e186d0a1b95620b49',
    'ded1086272c03586a4f71f6acf7f98d5210c79f3d7e2a693dae20f83780f1d36',
    'd78feb97d008556988cdb74b4c4877dd3db50ae5b2bb3bf1d56c8117bf73675a',
    '02e1d7610504a860fff784c273b2850d2ecdf03d37d3b8e2afb28963d2ac5d9c',
    'c60d925110b93399bb2320e5c322fb15e6dc75dbb89c5cdd9d5dff1773d553b5',
    'a10544c25b83bcf966162dcfa2ff35f3f208310f5871c636fbae9866d45c0b45',
    '85eb4cdf1940c0832affd6362279513fa2f31d00dd9ce606e0e5bb444d34b44c',
    '0c328f1177625641d26dc536fbd5f19385468860b56291283271cb6875426ca0',
    '615f356a1a3a186d7fda071b66b9f4d4c415016d35014a88fa9931735ee79119',
    '67cb546bdad9cae81e893c5964e22d3001af9019d8b20f990050d9868440422c',
    '52811f5e70b4b14144807f1352abc4684a4331314a014a45bd0db89c5dbcd23c',
    'bd5e84b15275558ba89322651c4b113b33d28116e304ee970ce6d1c7a3951e25',
    '1419ca7648f3dd4c9822b4506f97f6d258a7ff09243eaaf805e7c2ffcfd3d5de',
    '43e2a7151ab692f6fd1c1f66a404f10e7184c708dd40121f3c175e760f90cfa9',
    '59cb34cbcdc44cfc206d394924b2a97d8560703c3abb433e99a9b2541a72b2eb',
    '80fe681ebd85ff947a639aa0e1e7c1396f1002e75b57dda7100912f976092b7d',
    'aa174031025d53e170c8affae179c6c84a5a104fc56a3b59e9e3d87d3f7b3c6b',
    '03e78f46d81087ae13c21dcd6be01e4011e7ac8bafaf92a5b4be825082752eb8',
    '0c205021bc1b7d7dd9826c18ce3b5c3aec2065afe6b5a967a6f80dc4fb83e83a',
    'b3ef2447c6ecfa7b40d081adb1bfcd2b7be052974642ec049b2ce72e436f985e',
    '922e97f16cc5bf8a6693aea9b36bc5ab1dea78fba91cc0bf887504450020c63f',
    '86dd2cea19f39b903165fd9672a067efc60574a9eb2a1db0f42124cd79a6e26d',
    '029ce82a403833ee41c2b77f3a602d5e6a94343f3d28fe487047d192b42bb5e2',
    'c08f9864c704cc90bc8a6ce327821af25fa5cf037cf5b3af1bae62196940019e',
    '04b66986b8233c9b91cb3237ed71459060f867da244208bde9b88901bae4a2de',
    '53a9c890ec89b1640045463001c52f7b062f374c41826561ebee8c4df147b55b',
    '9473f0d658e83ed20afdf7deb3667005e1f9abad9a8e9ea6b234c925e8c4a12d',
    'bdfd6e82e051f2e7c4d844c9b259525d1c397ebff458e7a5f68dfb2ed196b924',
    'f0784870396c52916ceabe585f7aa98c8acddbeebda4a2f524ef25d00520a669',
    '8cd917d1cc7e274eb93041002e0495fdfbb71a125289104aa920085fec5b99ff',
    'b0919739011fc721e05442937a51dc81f0ffcf216c81e48f0f24cec673aab06f',
    '77131906691ca0705d0261d5adb868e34e7257dae1a5253d2ee75b9e5b6fffc9',
    '9c6455917c0f03e81660c2cbb9c9c81f64c7f07cad85c31eb55e7974ee2fd913',
    'd0516aa0830d5ebfa1ffa762b3b0fa40e336158aabb9755a3a80a62a6363c92d',
    'e226fe65aca5e258ca33d5f6171064476547f6c0b8805a1978179aba60d32db7',
)


def _require_spec(actual, expected, *, kind: str, index: int) -> None:
    if actual != expected:
        raise PublicationContractError(
            f"Manual {kind} {index + 1} changed identity or order: "
            f"expected {expected!r}, found {actual!r}."
        )


def _table_content_sha256(block: tuple) -> str:
    payload = json.dumps(
        [
            [str(header) for header in block[1]],
            [[str(cell) for cell in row] for row in block[2]],
        ],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def publish_manual_blocks(
    blocks: Iterable[tuple],
) -> tuple[PublishedManualBlock, ...]:
    """Attach identities after validating every authored object in exact order."""

    if len(MANUAL_TABLE_CONTENT_SHA256) != len(MANUAL_TABLE_SPECS):
        raise PublicationContractError(
            "Manual table signatures and table specifications are misaligned."
        )
    published = []
    part = None
    section = None
    section_number = 0
    counter = None
    figure_index = 0
    table_index = 0

    for block in blocks:
        kind = block[0]
        alternative = None
        if kind == "part":
            part = str(block[1])
            match = re.match(r"^Part ([A-Z])\b", part)
            if match is None:
                raise PublicationContractError(
                    f"Manual part is not publication-safe: {part!r}."
                )
            part_code = match.group(1)
            section = None
            section_number = 0
            counter = None
        elif kind == "h1":
            if part is None:
                raise PublicationContractError(
                    "A manual section appeared before its part."
                )
            section = str(block[1])
            section_number += 1
            counter = PublicationCounter(f"{part_code}{section_number}", "-")

        item = None
        if kind == "figure":
            if counter is None or part is None or section is None:
                raise PublicationContractError(
                    "A manual figure appeared before its numbered section."
                )
            if figure_index >= len(MANUAL_FIGURE_SPECS):
                raise PublicationContractError("The manual contains an extra figure.")
            if len(block) != 4 or not str(block[3]).strip():
                raise PublicationContractError(
                    "A manual figure requires a non-empty authored text alternative."
                )
            actual = ManualFigureSpec(
                part,
                section,
                getattr(block[1], "__name__", ""),
                str(block[2]),
                str(block[3]),
            )
            expected = MANUAL_FIGURE_SPECS[figure_index]
            _require_spec(actual, expected, kind="figure", index=figure_index)
            item = counter.issue("Figure", expected.caption)
            alternative = expected.alternative
            figure_index += 1
        elif kind == "table":
            if counter is None or part is None or section is None:
                raise PublicationContractError(
                    "A manual table appeared before its numbered section."
                )
            if table_index >= len(MANUAL_TABLE_SPECS):
                raise PublicationContractError("The manual contains an extra table.")
            expected = MANUAL_TABLE_SPECS[table_index]
            actual = ManualTableSpec(
                part,
                section,
                tuple(str(header) for header in block[1]),
                expected.caption,
            )
            _require_spec(actual, expected, kind="table", index=table_index)
            if (
                _table_content_sha256(block)
                != MANUAL_TABLE_CONTENT_SHA256[table_index]
            ):
                raise PublicationContractError(
                    f"Manual table {table_index + 1} changed content or row order."
                )
            item = counter.issue("Table", expected.caption)
            table_index += 1
        published.append(PublishedManualBlock(block, item, alternative))

    if figure_index != len(MANUAL_FIGURE_SPECS):
        raise PublicationContractError(
            f"Expected {len(MANUAL_FIGURE_SPECS)} manual figures, "
            f"found {figure_index}."
        )
    if table_index != len(MANUAL_TABLE_SPECS):
        raise PublicationContractError(
            f"Expected {len(MANUAL_TABLE_SPECS)} manual tables, found {table_index}."
        )

    items = [entry.item for entry in published if entry.item is not None]
    labels = [item.label for item in items]
    anchors = [item.anchor for item in items]
    if len(labels) != len(set(labels)) or len(anchors) != len(set(anchors)):
        raise PublicationContractError(
            "Manual publication labels and anchors must be unique."
        )
    return tuple(published)


def published_manual_parts(
    blocks: Iterable[tuple],
) -> dict[str, list[PublishedManualBlock]]:
    """Group the validated stream without discarding publication identities."""

    parts = {}
    current = None
    for entry in publish_manual_blocks(blocks):
        if entry.block[0] == "part":
            current = entry.block[1]
            parts[current] = [entry]
        elif current is not None:
            parts[current].append(entry)
    return parts
