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
    ManualFigureSpec("Part A - Get started", "Quick start", "fig_beam_section",
                     "The rectangular worked example as Sector draws it: the concrete corners and bars are numbered. Use the *Display* controls beside your Section inputs to adjust label size and spacing.",
                     "A rectangular concrete outline with four numbered corner nodes, three numbered reinforcement bars near the lower face and two near the upper face."),
    ManualFigureSpec("Part A - Get started", "The worked examples", "fig_beam_section",
                     "Rectangular beam: 3 x 25 mm bottom, 2 x 16 mm top.",
                     "A 300 by 600 mm concrete rectangle with three bottom bars and two top bars arranged symmetrically about the vertical centreline."),
    ManualFigureSpec("Part A - Get started", "The worked examples", "fig_circular_section",
                     "Circular hollow section: a central void, a mild-bar ring and a tendon ring.",
                     "An annular concrete section with concentric outer and void boundaries; mild reinforcement and prestressing tendons form two circular rings."),
    ManualFigureSpec("Part B - Features & options", "Materials", "fig_beam_concrete_law",
                     "The concrete-law preview for the rectangular example (C40/50).",
                     "A compression stress-strain curve that rises parabolically from zero to the design strength and then remains horizontal to the ultimate strain."),
    ManualFigureSpec("Part B - Features & options", "Materials", "fig_beam_steel_law",
                     "The B550 mild-steel law for the rectangular example.",
                     "A symmetric reinforcing-steel stress-strain curve with linear tension and compression branches to yield followed by the selected post-yield response."),
    ManualFigureSpec("Part B - Features & options", "Materials", "fig_circular_prestress_law",
                     "The tendon law for the circular example.",
                     "A prestressing-steel stress-strain curve with an initial elastic branch and a nonlinear approach to design strength and ultimate strain."),
    ManualFigureSpec("Part B - Features & options", "Analysis & result settings", "fig_beam_envelope",
                     "The rectangular example's biaxial envelope with the applied load; the sweep from 0 to 360 degrees closes the curve.",
                     "A closed Mx-My capacity boundary around the origin with one applied-load point; successive boundary vertices correspond to rotated neutral-axis solutions."),
    ManualFigureSpec("Part C - Theory & methodology", "Conventions and sign convention", "fig_sign_convention",
                     "Axes and the positive senses of the axial force, the moments and the neutral-axis angle.",
                     "Section axes show positive x to the right and y upward, with arrows for positive axial force and moments and the neutral-axis angle measured from positive y."),
    ManualFigureSpec("Part C - Theory & methodology", "Material laws", "fig_beam_concrete_law",
                     "The C40/50 parabola-rectangle law of the beam example.",
                     "Concrete compression stress increases on a curved branch to its design plateau, which continues until the marked crushing strain."),
    ManualFigureSpec("Part C - Theory & methodology", "Material laws", "fig_beam_steel_law",
                     "The B550 mild-steel law of the beam example.",
                     "Positive and negative B550 stress branches are linear to the yield points and then follow matching post-yield branches toward the strain limits."),
    ManualFigureSpec("Part C - Theory & methodology", "Material laws", "fig_circular_prestress_law",
                     "The tendon law of the circular example.",
                     "The tendon curve starts with an elastic slope, bends toward the proof-strength region and terminates at the defined ultimate strain."),
    ManualFigureSpec("Part C - Theory & methodology", "Plastic capacity analysis", "fig_strain_plane",
                     "The capacity strain plane (reported tension-positive convention): one straight line -- zero at the neutral axis, compression (negative) above it and tension (positive) below, the top fibre at the crushing strain. The internal solver formula above is compression-positive; the reported strains negate it.",
                     "A straight strain line crosses zero at the neutral axis; negative compression lies above it, positive tension below it, and the top fibre reaches ultimate concrete compression."),
    ManualFigureSpec("Part C - Theory & methodology", "Plastic capacity analysis", "fig_beam_envelope",
                     "The beam envelope with its applied load; each vertex is one solved neutral-axis angle.",
                     "A closed biaxial moment-resistance curve is plotted with the design moment point, showing its position inside the boundary and the discrete angular sweep points."),
    ManualFigureSpec("Part C - Theory & methodology", "Cracked-section elastic analysis", "fig_beam_cracked",
                     "The beam's cracked (Stage II) state under the service moment: the compression zone (shaded) above the neutral axis.",
                     "A rectangular section has a shaded concrete compression zone above a horizontal neutral axis, with reinforcement points retained in the Stage II section."),
    ManualFigureSpec("Part C - Theory & methodology", "Grouped fatigue", "fig_fatigue_sn",
                     "Two-slope characteristic and design S-N curves. Each labelled marker is one applied spectrum bin; logarithmic axes retain the wide cycle and stress ranges without visual distortion.",
                     "A log-log stress-range versus cycles plot shows characteristic and design S-N curves with a knee and labelled spectrum-bin points on the relevant branches."),
    ManualFigureSpec("Part C - Theory & methodology", "Grouped fatigue", "fig_fatigue_damage",
                     "Per-bin and cumulative Miner damage for the same element. The cumulative line and $D=1.00$ limit make the governing contribution and remaining margin visible. The y-axis changes to a logarithmic scale for low-damage spectra so small contributions remain readable.",
                     "Damage bars identify each spectrum bin, a cumulative Miner-damage line rises across the bins, and a horizontal D equals 1 limit shows the remaining margin."),
)


MANUAL_TABLE_SPECS = (
    ManualTableSpec("Part A - Get started", "Start here",
                    ("Reading path", "Use it when", "Destination"),
                    "Manual reading paths"),
    ManualTableSpec("Part A - Get started", "Task workflows",
                    ("Workflow / outcome", "Before and do",
                     "Expected state / if blocked"),
                    "Task workflows and expected states"),
    ManualTableSpec("Part A - Get started", "The worked examples",
                    ("Example", "Section", "Reinforcement", "Demonstrates"),
                    "Worked-example section and reinforcement comparison"),
    ManualTableSpec("Part B - Features & options", "Input reference",
                    ("Application stage", "Manual destination"),
                    "Application input stages and manual destinations"),
    ManualTableSpec("Part B - Features & options", "The workspace",
                    ("View", "Shows"),
                    "Analysis result views and their reported information"),
    ManualTableSpec("Part B - Features & options", "Defining the section",
                    ("Size basis", "Entered", "Calculated"),
                    "Reinforcement size input bases"),
    ManualTableSpec("Part B - Features & options", "Defining the section",
                    ("Shape", "Produces"), "Quick Section builder shapes"),
    ManualTableSpec("Part B - Features & options", "Analysis & result settings",
                    ("Section cut", "Canonical modelled reinforcement direction"),
                    "Section cuts and canonical modelled reinforcement directions"),
    ManualTableSpec("Part B - Features & options", "Analysis & result settings",
                    ("Member", "Vertical shear-link spacing limits"),
                    "Vertical shear-link spacing limits"),
    ManualTableSpec("Part B - Features & options", "Analysis & result settings",
                    ("Edition", "Minimum-reinforcement method"),
                    "Minimum-reinforcement methods by edition"),
    ManualTableSpec("Part B - Features & options", "Analysis & result settings",
                    ("Crack-width code", "What it changes"),
                    "Crack-width method differences"),
    ManualTableSpec("Part B - Features & options", "Analysis & result settings",
                    ("Input", "Use"), "Grouped-fatigue input fields"),
    ManualTableSpec("Part B - Features & options", "Analysis & result settings",
                    ("Fatigue edition", "Implemented resistance basis"),
                    "Fatigue resistance bases by edition"),
    ManualTableSpec("Part B - Features & options", "Analysis & result settings",
                    ("Component", "Geometry and associated bending"),
                    "Shear components and associated bending"),
    ManualTableSpec("Part B - Features & options", "Analysis & result settings",
                    ("Shear method", "What it sets"),
                    "Implemented shear methods"),
    ManualTableSpec("Part B - Features & options", "Loads",
                    ("Table", "Per-row fields", "Row-specific rule"),
                    "Action tables, row fields and row-specific rules"),
    ManualTableSpec("Part B - Features & options", "Loads",
                    ("Editable table", "Fields / notation", "Blank / default"),
                    "Editable-table fields, notation and blank/default contracts"),
    ManualTableSpec("Part B - Features & options", "Loads",
                    ("Table", "Field / notation", "Definition and sign",
                     "Blank/default and validation", "Method dependency"),
                    "Editable-table field definitions, validation and dependencies"),
    ManualTableSpec("Part B - Features & options", "Reading the results",
                    ("Profile", "Purpose", "Declared omitted detail"),
                    "Report profiles and presentation depth"),
    ManualTableSpec("Part C - Theory & methodology", "Method reference",
                    ("Engineering task", "Method destination"),
                    "Engineering method reference destinations"),
    ManualTableSpec("Part C - Theory & methodology", "Serviceability: cracking and crack width",
                    ("Crack-width edition", "$s_{r,max}$ (mm)", "$h_{c,ef}$ (m)", "$w_k$ (mm)"),
                    "Worked crack-width comparison by edition"),
    ManualTableSpec("Part C - Theory & methodology", "Grouped fatigue",
                    ("Fatigue basis and named detail", "Simplified limit"),
                    "Simplified reinforcement fatigue stress-range limits"),
    ManualTableSpec("Part C - Theory & methodology", "Grouped fatigue",
                    ("Edition", "Reinforcement", "Concrete", "Mixed bond"),
                    "Fatigue editions, reinforcement scope and concrete scope"),
    ManualTableSpec("Part D - Reference", "Standards", ("Topic", "Reference"),
                    "Standards and reference sources"),
    ManualTableSpec("Part D - Reference", "Limitations & troubleshooting",
                    ("Symptom", "Likely cause", "Correction"),
                    "Troubleshooting symptoms, causes and corrections"),
    ManualTableSpec("Part D - Reference", "Glossary", ("Symbol / term", "Meaning"),
                    "Glossary of symbols and terms"),
)


# SHA-256 of each exact ordered ``(headers, rows)`` payload on the accepted
# base. Headers keep the contract reviewable; the digest also rejects a
# same-header replacement or row reorder that would otherwise look identical.
MANUAL_TABLE_CONTENT_SHA256 = (
    "be08991cf6c78e87a479cb56daf4b0d37bd0d95186bf1bde11f9a80768db09ab",
    "26ed31e0a369cab56d473505b85ea24f27c6119f10532a285dce8c1d2fd48f92",
    "dfc12f2afad4b9961ecc50234ff2717edd71655ce2bee317fa560d7b697525b6",
    "c57b1f9833250de5684b679bcfc052f15bad2be7ba78bcfbf218a880eace69a2",
    "b174acc1fa302cc5034d9e1f83cf89165e080edcb54f2a945b39c7115bf24f58",
    "b972bfbfeb72f66d02898862d2af8e0ec6837629130b1fd333213cbd26ece414",
    "1f3edbeb8f4f07cafeb123f8c0284a0f870a40ee8395d3a67cb210b86ab64242",
    "8338dced26a065265c77b48225f95c8fcf15c51fca7d4cf5b8f0bc89430e9161",
    "e1805fa14f8c0fc53f79bdc7c4b35c2774c4ed664f53b1d46f51f10ab78ea70b",
    "a7fdb1c7ca70ba4ab7ae4253de37420e3e743587c165479ca5289db495967888",
    "1af0a9aaabd06d956b2c2da512b177a7f5e7fff8efcbaae736497db6eca6fc15",
    "27691aed4aa5e45bcf516489b3338acbab1485118d25c8e530431ab6654e9fe3",
    "8fcfe95e26ac6b8baca7437cdc33ab8cad71b913b4536254648c6f57b4bf6c70",
    "86092aa2081aaea15fd442cd36e7f8e350dbd4b4528abb29746825030c0a107e",
    "afe5a0665a62f5c418f11a600bd157643e3ea8bdecb9de77b70651e9ac801538",
    "7626d90edb81ce4dad70867b5573a36e1ff97730314b6cdd74297084eef78f9c",
    "8696161a7b88710f4e8921e000b4c89484b2ff4a3119268200fce3c64503c9b5",
    "c6beadbac21bc97dcb699d63fd0dc73006fafcaa6aa10a7d8d7058aea6a8cd9e",
    "38dd54ea274e30ede3642ffb17c6b3e978bfb43c9d167781bf05b8d5c211b5cd",
    "0983c6e55bb7b8362d84908e942e1917eaf516c67844767ce7a6138caf6286e5",
    "2e3abdbf91949a69ee3fdab2c8d39335bf175d1ea5d7af38116c872f4666b1ce",
    "8421c672f3864d2127c4c661fea52d2ceab85038275ab7e3093b846b07e4fe71",
    "62a58fd92caebabf1711340262c71c619808090ca0a1236a59b965921b1076c9",
    "d0d10014b82614ece2fc39112a56e8c98a9424539ea58c3824d1781746f76026",
    "d4ef9164470ea3c81d30d0b455cb177f765010b96a26f8cf90eca61fefe8d09f",
    "1b81f6d383a3c85b149dabf88512656fe900229f30927e1af4aba27dbcd90781",
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
