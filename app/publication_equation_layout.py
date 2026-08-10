"""Strict, shared ReportLab layout for publication equations.

The module deliberately owns presentation only.  It compiles either Sector's
trusted report-markup subset or the manual's trusted TeX subset into a frozen
display tree, measures that tree, and draws searchable text plus vector rules.
It does not know about calculation results, equation catalogues, sources,
dependencies, or application state.

All source stays ASCII.  Mathematical Unicode characters are introduced from
numeric code points at runtime so the repository-wide ASCII guard remains
effective.
"""

from __future__ import annotations

import html
import math
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, TypeAlias

if TYPE_CHECKING:
    class _FontFace(Protocol):
        charWidths: dict[int, float]


    class TTFont:
        face: _FontFace

        def __init__(self, name: str, filename: str) -> None:
            pass


    class _PdfMetrics(Protocol):
        def getRegisteredFontNames(self) -> list[str]: ...

        def registerFont(self, font: TTFont) -> None: ...

        def getFont(self, name: str) -> object: ...

        def getAscentDescent(self, name: str, size: float) -> tuple[float, float]: ...

        def stringWidth(self, text: str, name: str, size: float) -> float: ...


    class _Colors(Protocol):
        def HexColor(self, value: str) -> object: ...


    class _TextObject(Protocol):
        def setFont(self, name: str, size: float) -> None: ...

        def setTextRenderMode(self, mode: int) -> None: ...

        def setTextTransform(
            self,
            a: float,
            b: float,
            c: float,
            d: float,
            e: float,
            f: float,
        ) -> None: ...

        def textOut(self, text: str) -> None: ...


    class Canvas(Protocol):
        def saveState(self) -> None: ...

        def restoreState(self) -> None: ...

        def setFillColor(self, color: object) -> None: ...

        def beginText(self) -> _TextObject: ...

        def drawText(self, text: _TextObject) -> None: ...

        def setStrokeColor(self, color: object) -> None: ...

        def setLineWidth(self, width: float) -> None: ...

        def line(self, x1: float, y1: float, x2: float, y2: float) -> None: ...


    class Flowable:
        canv: Canvas
        width: float
        height: float

        def __init__(self) -> None:
            pass


    colors: _Colors
    pdfmetrics: _PdfMetrics
else:
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.platypus import Flowable


class EquationLayoutError(ValueError):
    """Raised before publication when equation syntax or geometry is unsafe."""


class EquationFontError(EquationLayoutError):
    """Raised when the required embedded font or one of its glyphs is absent."""


_DEFAULT_REGULAR_FONT: Final = "SectorEquationSans"
_DEFAULT_BOLD_FONT: Final = "SectorEquationSans-Bold"
_FONT_FILES: Final = {
    _DEFAULT_REGULAR_FONT: "DejaVuSans.ttf",
    _DEFAULT_BOLD_FONT: "DejaVuSans-Bold.ttf",
}
_FONT_DIRECTORY: Final = Path(__file__).resolve().parent / "assets" / "fonts"
_PLAIN_ROLE_RE: Final = re.compile(r"[a-z][a-z0-9-]*")
_COLOR_RE: Final = re.compile(r"#[0-9A-Fa-f]{6}")
_NUMBER_RE: Final = re.compile(
    r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
)
_REPORT_ENTITY_RE: Final = re.compile(
    r"&(?:#\d+|#x[0-9A-Fa-f]+|lt|gt|amp|nbsp);"
)
_REPORT_TAG_RE: Final = re.compile(r"</?(?:sub|super|sup)>")
_REPORT_SCRIPT_RE: Final = re.compile(
    r"<(sub|super|sup)>((?:(?!</?(?:sub|super|sup)>).)*)</\1>",
    flags=re.DOTALL,
)

_EPSILON: Final = chr(0x03B5)
_SIGMA: Final = chr(0x03C3)
_LAMBDA: Final = chr(0x03BB)
_ALPHA: Final = chr(0x03B1)
_BETA: Final = chr(0x03B2)
_ETA: Final = chr(0x03B7)
_GAMMA: Final = chr(0x03B3)
_KAPPA: Final = chr(0x03BA)
_RHO: Final = chr(0x03C1)
_PHI: Final = chr(0x03C6)
_THETA: Final = chr(0x03B8)
_NU: Final = chr(0x03BD)
_TAU: Final = chr(0x03C4)
_XI: Final = chr(0x03BE)
_PI: Final = chr(0x03C0)
_DELTA: Final = chr(0x0394)
_SUM: Final = chr(0x2211)
_SQRT: Final = chr(0x221A)
_LE: Final = chr(0x2264)
_GE: Final = chr(0x2265)
_NE: Final = chr(0x2260)
_TIMES: Final = chr(0x00D7)
_DOT: Final = chr(0x00B7)
_APPROX: Final = chr(0x2248)
_PLUS_MINUS: Final = chr(0x00B1)
_DEGREE: Final = chr(0x00B0)
_ARROW: Final = chr(0x2192)
_PER_MILLE: Final = chr(0x2030)
_INFINITY: Final = chr(0x221E)
_OVERBAR: Final = chr(0x0304)
_HALF: Final = chr(0x00BD)

_GREEK_NAMES: Final = {
    "eps": _EPSILON,
    "varepsilon": _EPSILON,
    "epsilon": _EPSILON,
    "sigma": _SIGMA,
    "lambda": _LAMBDA,
    "alpha": _ALPHA,
    "beta": _BETA,
    "eta": _ETA,
    "gamma": _GAMMA,
    "kappa": _KAPPA,
    "rho": _RHO,
    "phi": _PHI,
    "varphi": _PHI,
    "theta": _THETA,
    "nu": _NU,
    "tau": _TAU,
    "xi": _XI,
    "pi": _PI,
    "Delta": _DELTA,
}
_FUNCTION_NAMES: Final = frozenset(
    ("min", "max", "ln", "log", "sin", "cos", "tan", "cot", "abs")
)
_UNIT_NAMES: Final = frozenset(
    (
        "N",
        "kN",
        "Nm",
        "kNm",
        "Pa",
        "kPa",
        "MPa",
        "GPa",
        "m",
        "mm",
        "cm",
        "rad",
        "deg",
        "percent",
        "permille",
    )
)
_AMBIGUOUS_UNIT_NAMES: Final = frozenset(("N", "m"))
_RELATIONS: Final = frozenset(("=", _LE, _GE, "<", ">", _NE, _APPROX, _ARROW))
_BREAK_OPERATORS: Final = frozenset(
    ("+", "-", _PLUS_MINUS, ",", ";", ".", *_RELATIONS)
)
_BINARY_PRECEDENCE: Final = {
    ",": 1,
    ";": 1,
    ".": 1,
    "=": 2,
    _LE: 2,
    _GE: 2,
    "<": 2,
    ">": 2,
    _NE: 2,
    _APPROX: 2,
    _ARROW: 2,
    "+": 3,
    "-": 3,
    _PLUS_MINUS: 3,
    "*": 4,
    _DOT: 4,
    _TIMES: 4,
    "/": 4,
    ":": 5,
}


def _require_plain_text(value: str, label: str, *, allow_empty: bool = False) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be text.")
    if not allow_empty and not value.strip():
        raise EquationLayoutError(f"{label} must not be empty.")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise EquationLayoutError(f"{label} contains a control character.")
    if "<" in value or ">" in value or "\\" in value or "$" in value:
        raise EquationLayoutError(f"{label} contains raw markup or TeX.")


def _require_semantic_text(value: str, label: str) -> None:
    """Validate already-normalized searchable text that is never markup-parsed."""

    if not isinstance(value, str):
        raise TypeError(f"{label} must be text.")
    if not value.strip():
        raise EquationLayoutError(f"{label} must not be empty.")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise EquationLayoutError(f"{label} contains a control character.")
    if "\\" in value or "$" in value:
        raise EquationLayoutError(f"{label} contains raw TeX.")
    if re.search(
        r"</?(?:a|b|br|font|i|link|sub|sup|super)\b[^>]*>",
        value,
        flags=re.IGNORECASE,
    ):
        raise EquationLayoutError(f"{label} contains raw markup.")


@dataclass(frozen=True, slots=True)
class EquationFonts:
    """Required embedded faces plus the deliberate scalar slant transform."""

    regular: str = _DEFAULT_REGULAR_FONT
    bold: str = _DEFAULT_BOLD_FONT
    scalar_slant: float = 0.18

    def __post_init__(self) -> None:
        _require_plain_text(self.regular, "regular font")
        _require_plain_text(self.bold, "bold font")
        if not math.isfinite(self.scalar_slant) or not 0.08 <= self.scalar_slant <= 0.30:
            raise EquationFontError(
                "scalar slant must be a deliberate finite transform from 0.08 to 0.30."
            )


@dataclass(frozen=True, slots=True)
class EquationStyle:
    """Complete immutable geometry and colour contract for one equation block."""

    fonts: EquationFonts = EquationFonts()
    font_size: float = 10.0
    label_size: float = 8.2
    source_size: float = 7.8
    identity_size: float = 8.2
    left_indent: float = 12.0
    right_indent: float = 6.0
    top_padding: float = 3.0
    bottom_padding: float = 3.0
    label_gap: float = 8.0
    row_gap: float = 4.0
    source_gap: float = 5.0
    identity_gap: float = 8.0
    maximum_height: float = 700.0
    ink: str = "#202020"
    muted_ink: str = "#5A5A5A"

    def __post_init__(self) -> None:
        positive = (
            self.font_size,
            self.label_size,
            self.source_size,
            self.identity_size,
            self.label_gap,
            self.row_gap,
            self.source_gap,
            self.identity_gap,
            self.maximum_height,
        )
        nonnegative = (
            self.left_indent,
            self.right_indent,
            self.top_padding,
            self.bottom_padding,
        )
        if any(not math.isfinite(value) or value <= 0.0 for value in positive):
            raise EquationLayoutError("equation style dimensions must be finite and positive.")
        if any(not math.isfinite(value) or value < 0.0 for value in nonnegative):
            raise EquationLayoutError(
                "equation style indents and padding must be finite and non-negative."
            )
        if self.font_size < 7.5 or self.label_size < 7.0 or self.source_size < 7.0:
            raise EquationLayoutError("equation typography is below the legibility floor.")
        if not _COLOR_RE.fullmatch(self.ink) or not _COLOR_RE.fullmatch(self.muted_ink):
            raise EquationLayoutError("equation colours must be six-digit hex values.")


DEFAULT_EQUATION_STYLE: Final = EquationStyle()


class MathNode:
    """Closed marker base for the immutable publication display tree."""

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class Variable(MathNode):
    text: str

    def __post_init__(self) -> None:
        _require_plain_text(self.text, "variable")
        if not all(character.isalpha() for character in self.text):
            raise EquationLayoutError("a scalar variable must contain letters only.")


@dataclass(frozen=True, slots=True)
class Upright(MathNode):
    text: str

    def __post_init__(self) -> None:
        _require_plain_text(self.text, "upright text")
        if not all(
            character.isalnum() or character in " .,_:-" for character in self.text
        ):
            raise EquationLayoutError("upright text contains unsupported punctuation.")


@dataclass(frozen=True, slots=True)
class Number(MathNode):
    text: str

    def __post_init__(self) -> None:
        _require_plain_text(self.text, "number")
        if _NUMBER_RE.fullmatch(self.text) is None:
            raise EquationLayoutError(f"invalid publication number: {self.text!r}.")


@dataclass(frozen=True, slots=True)
class Operator(MathNode):
    text: str

    def __post_init__(self) -> None:
        _require_plain_text(self.text, "operator")
        supported = set(_BINARY_PRECEDENCE) | {
            _SUM,
            _SQRT,
            _DEGREE,
            _PER_MILLE,
            _INFINITY,
            "%",
            "|",
            ".",
        }
        if self.text not in supported:
            raise EquationLayoutError(f"unsupported mathematical operator: {self.text!r}.")


@dataclass(frozen=True, slots=True)
class Unit(MathNode):
    text: str

    def __post_init__(self) -> None:
        _require_plain_text(self.text, "unit")
        if self.text not in _UNIT_NAMES and not re.fullmatch(
            r"[A-Za-z%]+(?:[*/.-][A-Za-z0-9%]+)*", self.text
        ):
            raise EquationLayoutError(f"unsupported publication unit: {self.text!r}.")


@dataclass(frozen=True, slots=True)
class LiteralText(MathNode):
    """Explicit, upright report result/verdict text; never parsed as mathematics."""

    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise EquationLayoutError("literal report text must not be empty.")
        if any(ord(character) < 32 or ord(character) == 127 for character in self.text):
            raise EquationLayoutError("literal report text contains a control character.")
        if any(character in self.text for character in "\\${}"):
            raise EquationLayoutError("literal report text contains raw TeX or braces.")
        if re.search(r"</?[A-Za-z]", self.text):
            raise EquationLayoutError("literal report text contains raw markup.")


@dataclass(frozen=True, slots=True)
class MathSpace(MathNode):
    em: float = 0.22

    def __post_init__(self) -> None:
        if not math.isfinite(self.em) or not 0.05 <= self.em <= 2.0:
            raise EquationLayoutError("math space must be a finite value from 0.05 to 2 em.")


@dataclass(frozen=True, slots=True)
class MathSequence(MathNode):
    items: tuple[MathNode, ...]

    def __post_init__(self) -> None:
        if type(self.items) is not tuple:
            raise TypeError("math sequence items must be an exact tuple.")
        if not self.items:
            raise EquationLayoutError("a math sequence requires a non-empty tuple.")
        if not all(isinstance(item, MathNode) for item in self.items):
            raise TypeError("math sequence items must be MathNode values.")


@dataclass(frozen=True, slots=True)
class Fraction(MathNode):
    numerator: MathNode
    denominator: MathNode

    def __post_init__(self) -> None:
        if not isinstance(self.numerator, MathNode) or not isinstance(
            self.denominator, MathNode
        ):
            raise TypeError("fraction operands must be MathNode values.")


@dataclass(frozen=True, slots=True)
class Radical(MathNode):
    radicand: MathNode
    index: MathNode | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.radicand, MathNode):
            raise TypeError("a radical radicand must be a MathNode value.")
        if self.index is not None and not isinstance(self.index, MathNode):
            raise TypeError("a radical index must be a MathNode value.")


@dataclass(frozen=True, slots=True)
class Script(MathNode):
    base: MathNode
    subscript: MathNode | None = None
    superscript: MathNode | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.base, MathNode):
            raise TypeError("a script base must be a MathNode value.")
        if self.subscript is None and self.superscript is None:
            raise EquationLayoutError("a script requires a subscript or superscript.")
        if self.subscript is not None and not isinstance(self.subscript, MathNode):
            raise TypeError("a subscript must be a MathNode value.")
        if self.superscript is not None and not isinstance(self.superscript, MathNode):
            raise TypeError("a superscript must be a MathNode value.")


@dataclass(frozen=True, slots=True)
class Overbar(MathNode):
    base: MathNode

    def __post_init__(self) -> None:
        if not isinstance(self.base, MathNode):
            raise TypeError("an overbar base must be a MathNode value.")


@dataclass(frozen=True, slots=True)
class RelationFragment(MathNode):
    """Explicit substitution/result fragment beginning with a relation."""

    relation: Operator
    right: MathNode

    def __post_init__(self) -> None:
        if type(self.relation) is not Operator or self.relation.text not in _RELATIONS:
            raise EquationLayoutError("a relation fragment requires one relation operator.")
        if not isinstance(self.right, MathNode):
            raise TypeError("a relation-fragment right operand must be a MathNode value.")


@dataclass(frozen=True, slots=True)
class Delimited(MathNode):
    content: MathNode
    left: str = "("
    right: str = ")"

    def __post_init__(self) -> None:
        if not isinstance(self.content, MathNode):
            raise TypeError("delimited content must be a MathNode value.")
        if (self.left, self.right) not in {
            ("(", ")"),
            ("[", "]"),
            ("|", "|"),
        }:
            raise EquationLayoutError("unsupported or unbalanced delimiters.")


MathTree: TypeAlias = (
    Variable
    | Upright
    | Number
    | Operator
    | Unit
    | LiteralText
    | MathSpace
    | MathSequence
    | Fraction
    | Radical
    | Script
    | Overbar
    | RelationFragment
    | Delimited
)


def math_sequence(*items: MathNode) -> MathNode:
    """Return a flattened immutable sequence without leading/trailing spaces."""

    flattened: list[MathNode] = []
    for item in items:
        if not isinstance(item, MathNode):
            raise TypeError("math_sequence accepts MathNode values only.")
        values = item.items if isinstance(item, MathSequence) else (item,)
        for value in values:
            if isinstance(value, MathSpace) and (
                not flattened or isinstance(flattened[-1], MathSpace)
            ):
                continue
            flattened.append(value)
    while flattened and isinstance(flattened[-1], MathSpace):
        flattened.pop()
    if not flattened:
        raise EquationLayoutError("a math sequence must not be empty.")
    if len(flattened) == 1:
        return flattened[0]
    return MathSequence(tuple(flattened))


@dataclass(frozen=True, slots=True)
class EquationLine:
    role: str
    expression: MathNode
    label: str | None = None
    semantic_text: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.role, str) or _PLAIN_ROLE_RE.fullmatch(self.role) is None:
            raise EquationLayoutError(f"invalid equation-line role: {self.role!r}.")
        if not isinstance(self.expression, MathNode):
            raise TypeError("an equation line requires a MathNode expression.")
        if self.label is not None:
            _require_plain_text(self.label, "equation-line label")
        if self.semantic_text is not None:
            _require_semantic_text(
                self.semantic_text,
                "equation-line semantic text",
            )


@dataclass(frozen=True, slots=True)
class EquationBlock:
    lines: tuple[EquationLine, ...]
    identity: str | None = None
    source: str | None = None

    def __post_init__(self) -> None:
        if type(self.lines) is not tuple:
            raise TypeError("equation block lines must be an exact tuple.")
        if not self.lines:
            raise EquationLayoutError("an equation block requires a non-empty tuple.")
        if not all(type(line) is EquationLine for line in self.lines):
            raise TypeError("equation block lines must be exact EquationLine values.")
        if self.identity is not None:
            _require_plain_text(self.identity, "equation identity")
        if self.source is not None:
            _require_plain_text(self.source, "equation source")


@dataclass(frozen=True, slots=True)
class Bounds:
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def top(self) -> float:
        return self.y + self.height


@dataclass(frozen=True, slots=True)
class TextPlacement:
    text: str
    x: float
    baseline: float
    font_name: str
    font_size: float
    slant: float
    color: str
    role: str
    render_mode: int = 0


@dataclass(frozen=True, slots=True)
class RulePlacement:
    x1: float
    y1: float
    x2: float
    y2: float
    thickness: float
    color: str
    role: str


@dataclass(frozen=True, slots=True)
class NodePlacement:
    kind: str
    bounds: Bounds


@dataclass(frozen=True, slots=True)
class MathLayout:
    width: float
    height: float
    baseline: float
    texts: tuple[TextPlacement, ...]
    rules: tuple[RulePlacement, ...]
    nodes: tuple[NodePlacement, ...]

    def __post_init__(self) -> None:
        collections = (
            (self.texts, TextPlacement, "math-layout texts"),
            (self.rules, RulePlacement, "math-layout rules"),
            (self.nodes, NodePlacement, "math-layout nodes"),
        )
        for values, expected, label in collections:
            if type(values) is not tuple:
                raise TypeError(f"{label} must be an exact tuple.")
            if not all(type(value) is expected for value in values):
                raise TypeError(f"{label} contain an invalid placement.")


@dataclass(frozen=True, slots=True)
class EquationRowLayout:
    role: str
    bounds: Bounds
    relation_x: float | None
    continuation: bool


@dataclass(frozen=True, slots=True)
class EquationGeometry:
    width: float
    height: float
    texts: tuple[TextPlacement, ...]
    rules: tuple[RulePlacement, ...]
    nodes: tuple[NodePlacement, ...]
    rows: tuple[EquationRowLayout, ...]

    def __post_init__(self) -> None:
        collections = (
            (self.texts, TextPlacement, "equation-geometry texts"),
            (self.rules, RulePlacement, "equation-geometry rules"),
            (self.nodes, NodePlacement, "equation-geometry nodes"),
            (self.rows, EquationRowLayout, "equation-geometry rows"),
        )
        for values, expected, label in collections:
            if type(values) is not tuple:
                raise TypeError(f"{label} must be an exact tuple.")
            if not all(type(value) is expected for value in values):
                raise TypeError(f"{label} contain an invalid placement.")


def register_default_equation_fonts() -> EquationFonts:
    """Register the bundled faces or fail without a Helvetica fallback."""

    registered = set(pdfmetrics.getRegisteredFontNames())
    for name, filename in _FONT_FILES.items():
        if name in registered:
            continue
        path = _FONT_DIRECTORY / filename
        if not path.is_file():
            raise EquationFontError(f"required equation font is missing: {filename}.")
        try:
            pdfmetrics.registerFont(TTFont(name, str(path)))
        except Exception as exc:
            raise EquationFontError(
                f"required equation font cannot be registered: {filename}."
            ) from exc
    return EquationFonts()


def _font(font_name: str) -> TTFont:
    if font_name in _FONT_FILES:
        register_default_equation_fonts()
    try:
        value = pdfmetrics.getFont(font_name)
    except KeyError as exc:
        raise EquationFontError(f"required equation font is not registered: {font_name}.") from exc
    if not isinstance(value, TTFont):
        raise EquationFontError(
            f"equation font must be an embedded TrueType face: {font_name}."
        )
    return value


def _require_glyphs(font_name: str, text: str) -> None:
    font = _font(font_name)
    widths = font.face.charWidths
    missing = sorted({ord(character) for character in text if ord(character) not in widths})
    if missing:
        encoded = ", ".join(f"U+{code:04X}" for code in missing)
        raise EquationFontError(f"equation font {font_name} lacks glyphs: {encoded}.")


def _translate_bounds(bounds: Bounds, dx: float, dy: float) -> Bounds:
    return Bounds(bounds.x + dx, bounds.y + dy, bounds.width, bounds.height)


def _translate_layout(layout: MathLayout, dx: float, dy: float) -> MathLayout:
    return MathLayout(
        layout.width,
        layout.height,
        layout.baseline + dy,
        tuple(
            replace(text, x=text.x + dx, baseline=text.baseline + dy)
            for text in layout.texts
        ),
        tuple(
            replace(
                rule,
                x1=rule.x1 + dx,
                y1=rule.y1 + dy,
                x2=rule.x2 + dx,
                y2=rule.y2 + dy,
            )
            for rule in layout.rules
        ),
        tuple(
            replace(node, bounds=_translate_bounds(node.bounds, dx, dy))
            for node in layout.nodes
        ),
    )


def _text_layout(
    text: str,
    *,
    font_name: str,
    font_size: float,
    slant: float,
    color: str,
    role: str,
    kind: str,
) -> MathLayout:
    _require_glyphs(font_name, text)
    ascent, descent = pdfmetrics.getAscentDescent(font_name, font_size)
    visible_width = pdfmetrics.stringWidth(text, font_name, font_size)
    slant_extension = max(0.0, slant * max(ascent, 0.0))
    width = visible_width + slant_extension
    height = ascent - descent
    baseline = -descent
    return MathLayout(
        width,
        height,
        baseline,
        (
            TextPlacement(
                text,
                0.0,
                baseline,
                font_name,
                font_size,
                slant,
                color,
                role,
                0,
            ),
        ),
        (),
        (NodePlacement(kind, Bounds(0.0, 0.0, width, height)),),
    )


def _space_layout(node: MathSpace, size: float) -> MathLayout:
    width = node.em * size
    return MathLayout(
        width,
        0.0,
        0.0,
        (),
        (),
        (NodePlacement("space", Bounds(0.0, 0.0, width, 0.0)),),
    )


def _sequence_layout(node: MathSequence, size: float, style: EquationStyle) -> MathLayout:
    children = [_layout_math(item, size, style) for item in node.items]
    baseline = max((child.baseline for child in children), default=0.0)
    above = max((child.height - child.baseline for child in children), default=0.0)
    height = baseline + above
    x = 0.0
    texts: list[TextPlacement] = []
    rules: list[RulePlacement] = []
    nodes: list[NodePlacement] = []
    for child in children:
        moved = _translate_layout(child, x, baseline - child.baseline)
        texts.extend(moved.texts)
        rules.extend(moved.rules)
        nodes.extend(moved.nodes)
        x += child.width
    nodes.append(NodePlacement("sequence", Bounds(0.0, 0.0, x, height)))
    return MathLayout(x, height, baseline, tuple(texts), tuple(rules), tuple(nodes))


def _fraction_layout(node: Fraction, size: float, style: EquationStyle) -> MathLayout:
    script_size = size * 0.82
    numerator = _layout_math(node.numerator, script_size, style)
    denominator = _layout_math(node.denominator, script_size, style)
    padding = size * 0.18
    gap = size * 0.12
    thickness = max(0.55, size * 0.055)
    width = max(numerator.width, denominator.width) + 2.0 * padding
    denominator_x = (width - denominator.width) / 2.0
    numerator_x = (width - numerator.width) / 2.0
    denominator_y = 0.0
    rule_y = denominator.height + gap
    numerator_y = rule_y + thickness + gap
    height = numerator_y + numerator.height
    baseline = max(denominator.baseline, rule_y - size * 0.28)
    moved_num = _translate_layout(numerator, numerator_x, numerator_y)
    moved_den = _translate_layout(denominator, denominator_x, denominator_y)
    rule = RulePlacement(
        padding * 0.45,
        rule_y,
        width - padding * 0.45,
        rule_y,
        thickness,
        style.ink,
        "fraction-rule",
    )
    nodes = (*moved_num.nodes, *moved_den.nodes)
    return MathLayout(
        width,
        height,
        baseline,
        (*moved_num.texts, *moved_den.texts),
        (*moved_num.rules, *moved_den.rules, rule),
        (*nodes, NodePlacement("fraction", Bounds(0.0, 0.0, width, height))),
    )


def _radical_layout(node: Radical, size: float, style: EquationStyle) -> MathLayout:
    radicand = _layout_math(node.radicand, size * 0.95, style)
    root_size = max(size, radicand.height * 1.08)
    root = _text_layout(
        _SQRT,
        font_name=style.fonts.regular,
        font_size=root_size,
        slant=0.0,
        color=style.ink,
        role="radical-sign",
        kind="radical-sign",
    )
    index = (
        _layout_math(node.index, size * 0.52, style)
        if node.index is not None
        else None
    )
    gap = size * 0.08
    thickness = max(0.55, size * 0.05)
    root_x = (
        max(0.0, index.width - root.width * 0.45)
        if index is not None
        else 0.0
    )
    radicand_x = root_x + root.width + gap * 0.2
    radicand_y = 0.0
    root_y = radicand.baseline - root.baseline
    minimum_y = min(0.0, root_y)
    shift = -minimum_y
    radicand_y += shift
    root_y += shift
    rule_y = radicand_y + radicand.height + gap
    moved_root = _translate_layout(root, root_x, root_y)
    moved_radicand = _translate_layout(radicand, radicand_x, radicand_y)
    width = radicand_x + radicand.width
    height = max(
        moved_root.nodes[-1].bounds.top if moved_root.nodes else 0.0,
        rule_y + thickness / 2.0,
    )
    baseline = radicand_y + radicand.baseline
    texts: tuple[TextPlacement, ...] = (*moved_root.texts, *moved_radicand.texts)
    rules: tuple[RulePlacement, ...] = (
        *moved_root.rules,
        *moved_radicand.rules,
        RulePlacement(
            radicand_x - gap * 0.1,
            rule_y,
            width,
            rule_y,
            thickness,
            style.ink,
            "radical-vinculum",
        ),
    )
    nodes: tuple[NodePlacement, ...] = (*moved_root.nodes, *moved_radicand.nodes)
    if index is not None:
        index_y = max(0.0, baseline + size * 0.30)
        moved_index = _translate_layout(index, 0.0, index_y)
        texts = (*texts, *moved_index.texts)
        rules = (*rules, *moved_index.rules)
        nodes = (*nodes, *moved_index.nodes)
        width = max(width, index.width)
        height = max(height, index_y + index.height)
    return MathLayout(
        width,
        height,
        baseline,
        texts,
        rules,
        (*nodes, NodePlacement("radical", Bounds(0.0, 0.0, width, height))),
    )


def _script_layout(node: Script, size: float, style: EquationStyle) -> MathLayout:
    base = _layout_math(node.base, size, style)
    subscript = (
        _layout_math(node.subscript, size * 0.68, style)
        if node.subscript is not None
        else None
    )
    superscript = (
        _layout_math(node.superscript, size * 0.68, style)
        if node.superscript is not None
        else None
    )
    script_x = max(0.0, base.width - size * 0.04)
    sub_y = (
        base.baseline - subscript.height * 0.72 - size * 0.08
        if subscript is not None
        else 0.0
    )
    super_y = (
        base.baseline + size * 0.38
        if superscript is not None
        else 0.0
    )
    shift = -min(0.0, sub_y)
    moved_base = _translate_layout(base, 0.0, shift)
    texts: tuple[TextPlacement, ...] = moved_base.texts
    rules: tuple[RulePlacement, ...] = moved_base.rules
    nodes: tuple[NodePlacement, ...] = moved_base.nodes
    width = base.width
    height = shift + base.height
    if subscript is not None:
        moved_sub = _translate_layout(subscript, script_x, sub_y + shift)
        texts = (*texts, *moved_sub.texts)
        rules = (*rules, *moved_sub.rules)
        nodes = (*nodes, *moved_sub.nodes)
        width = max(width, script_x + subscript.width)
        height = max(height, sub_y + shift + subscript.height)
    if superscript is not None:
        moved_super = _translate_layout(superscript, script_x, super_y + shift)
        texts = (*texts, *moved_super.texts)
        rules = (*rules, *moved_super.rules)
        nodes = (*nodes, *moved_super.nodes)
        width = max(width, script_x + superscript.width)
        height = max(height, super_y + shift + superscript.height)
    baseline = shift + base.baseline
    return MathLayout(
        width,
        height,
        baseline,
        texts,
        rules,
        (*nodes, NodePlacement("script", Bounds(0.0, 0.0, width, height))),
    )


def _overbar_layout(node: Overbar, size: float, style: EquationStyle) -> MathLayout:
    base = _layout_math(node.base, size, style)
    gap = size * 0.08
    thickness = max(0.55, size * 0.05)
    rule_y = base.height + gap
    height = rule_y + thickness / 2.0
    return MathLayout(
        base.width,
        height,
        base.baseline,
        base.texts,
        (
            *base.rules,
            RulePlacement(
                0.0,
                rule_y,
                base.width,
                rule_y,
                thickness,
                style.ink,
                "overbar-rule",
            ),
        ),
        (*base.nodes, NodePlacement("overbar", Bounds(0.0, 0.0, base.width, height))),
    )


def _delimiter_layout(node: Delimited, size: float, style: EquationStyle) -> MathLayout:
    content = _layout_math(node.content, size, style)
    delimiter_size = max(size, content.height * 1.08)
    left = _text_layout(
        node.left,
        font_name=style.fonts.regular,
        font_size=delimiter_size,
        slant=0.0,
        color=style.ink,
        role="delimiter",
        kind="delimiter",
    )
    right = _text_layout(
        node.right,
        font_name=style.fonts.regular,
        font_size=delimiter_size,
        slant=0.0,
        color=style.ink,
        role="delimiter",
        kind="delimiter",
    )
    baseline = max(left.baseline, content.baseline, right.baseline)
    above = max(
        left.height - left.baseline,
        content.height - content.baseline,
        right.height - right.baseline,
    )
    height = baseline + above
    gap = size * 0.08
    moved_left = _translate_layout(left, 0.0, baseline - left.baseline)
    content_x = left.width + gap
    moved_content = _translate_layout(
        content, content_x, baseline - content.baseline
    )
    right_x = content_x + content.width + gap
    moved_right = _translate_layout(right, right_x, baseline - right.baseline)
    width = right_x + right.width
    return MathLayout(
        width,
        height,
        baseline,
        (*moved_left.texts, *moved_content.texts, *moved_right.texts),
        (*moved_left.rules, *moved_content.rules, *moved_right.rules),
        (
            *moved_left.nodes,
            *moved_content.nodes,
            *moved_right.nodes,
            NodePlacement("delimited", Bounds(0.0, 0.0, width, height)),
        ),
    )


def _layout_math(node: MathNode, size: float, style: EquationStyle) -> MathLayout:
    if isinstance(node, Variable):
        return _text_layout(
            node.text,
            font_name=style.fonts.regular,
            font_size=size,
            slant=style.fonts.scalar_slant,
            color=style.ink,
            role="variable",
            kind="variable",
        )
    if isinstance(node, Upright):
        return _text_layout(
            node.text,
            font_name=style.fonts.regular,
            font_size=size,
            slant=0.0,
            color=style.ink,
            role="upright",
            kind="upright",
        )
    if isinstance(node, Number):
        return _text_layout(
            node.text,
            font_name=style.fonts.regular,
            font_size=size,
            slant=0.0,
            color=style.ink,
            role="number",
            kind="number",
        )
    if isinstance(node, Operator):
        return _text_layout(
            node.text,
            font_name=style.fonts.regular,
            font_size=size,
            slant=0.0,
            color=style.ink,
            role="operator",
            kind="operator",
        )
    if isinstance(node, Unit):
        return _text_layout(
            node.text,
            font_name=style.fonts.regular,
            font_size=size,
            slant=0.0,
            color=style.ink,
            role="unit",
            kind="unit",
        )
    if isinstance(node, LiteralText):
        return _text_layout(
            node.text,
            font_name=style.fonts.regular,
            font_size=size,
            slant=0.0,
            color=style.ink,
            role="literal",
            kind="literal",
        )
    if isinstance(node, MathSpace):
        return _space_layout(node, size)
    if isinstance(node, MathSequence):
        return _sequence_layout(node, size, style)
    if isinstance(node, Fraction):
        return _fraction_layout(node, size, style)
    if isinstance(node, Radical):
        return _radical_layout(node, size, style)
    if isinstance(node, Script):
        return _script_layout(node, size, style)
    if isinstance(node, Overbar):
        return _overbar_layout(node, size, style)
    if isinstance(node, RelationFragment):
        return _layout_math(
            math_sequence(node.relation, MathSpace(), node.right), size, style
        )
    if isinstance(node, Delimited):
        return _delimiter_layout(node, size, style)
    raise TypeError(f"unsupported MathNode type: {type(node).__name__}.")


def layout_math(
    node: MathNode,
    *,
    font_size: float = 10.0,
    style: EquationStyle = DEFAULT_EQUATION_STYLE,
) -> MathLayout:
    """Measure one immutable math tree without drawing it."""

    if not isinstance(node, MathNode):
        raise TypeError("layout_math requires a MathNode value.")
    if not math.isfinite(font_size) or font_size < 7.5:
        raise EquationLayoutError("math font size is below the legibility floor.")
    return _layout_math(node, font_size, style)


def _linear_text(node: MathNode) -> str:
    if isinstance(node, (Variable, Upright, Number, Operator, Unit, LiteralText)):
        return node.text
    if isinstance(node, MathSpace):
        return " "
    if isinstance(node, MathSequence):
        return "".join(_linear_text(item) for item in node.items)
    if isinstance(node, Fraction):
        return f"({_linear_text(node.numerator)}) / ({_linear_text(node.denominator)})"
    if isinstance(node, Radical):
        index = f"[{_linear_text(node.index)}]" if node.index is not None else ""
        return f"sqrt{index}({_linear_text(node.radicand)})"
    if isinstance(node, Script):
        text = _linear_text(node.base)
        if node.subscript is not None:
            text += f"_({_linear_text(node.subscript)})"
        if node.superscript is not None:
            text += f"^({_linear_text(node.superscript)})"
        return text
    if isinstance(node, Overbar):
        return f"overbar({_linear_text(node.base)})"
    if isinstance(node, RelationFragment):
        return f"{node.relation.text} {_linear_text(node.right)}"
    if isinstance(node, Delimited):
        return node.left + _linear_text(node.content) + node.right
    raise TypeError(f"unsupported MathNode type: {type(node).__name__}.")


def linear_math_text(node: MathNode) -> str:
    """Return deterministic searchable text for audit logs and tests."""

    return " ".join(_linear_text(node).split())


@dataclass(frozen=True, slots=True)
class _Token:
    kind: str
    value: str
    position: int


def _command_token(command: str, position: int) -> _Token | None:
    if command in _GREEK_NAMES:
        return _Token("IDENT", _GREEK_NAMES[command], position)
    if command in _FUNCTION_NAMES:
        return _Token("IDENT", command, position)
    mapping = {
        "frac": ("FRAC", ""),
        "tfrac": ("FRAC", ""),
        "sqrt": ("ROOT", "manual"),
        "mathrm": ("ROMAN", ""),
        "sum": ("IDENT", _SUM),
        "le": ("OP", _LE),
        "leq": ("OP", _LE),
        "ge": ("OP", _GE),
        "geq": ("OP", _GE),
        "neq": ("OP", _NE),
        "times": ("OP", _TIMES),
        "cdot": ("OP", _DOT),
        "approx": ("OP", _APPROX),
        "pm": ("OP", _PLUS_MINUS),
        "circ": ("IDENT", _DEGREE),
        "rightarrow": ("OP", _ARROW),
        "infty": ("IDENT", _INFINITY),
    }
    value = mapping.get(command)
    if value is not None:
        return _Token(value[0], value[1], position)
    if command in {"left", "right", "Big", "big", "Bigg", "bigg"}:
        return None
    if command in {"quad", "qquad", ",", ";", " "}:
        return _Token("SPACE", "2" if command in {"quad", "qquad"} else "1", position)
    if command == "!":
        return None
    raise EquationLayoutError(
        f"unsupported manual TeX command \\{command} at position {position}."
    )


def _raw_braced_text(source: str, start: int, label: str) -> tuple[str, int]:
    index = start
    while index < len(source) and source[index].isspace():
        index += 1
    if index >= len(source) or source[index] != "{":
        raise EquationLayoutError(f"{label} requires one braced operand at position {start}.")
    depth = 1
    end = index + 1
    while end < len(source) and depth:
        if source[end] == "{":
            depth += 1
        elif source[end] == "}":
            depth -= 1
        end += 1
    if depth:
        raise EquationLayoutError(f"unbalanced {label} braces at position {start}.")
    text = source[index + 1 : end - 1]
    _require_plain_text(text, label)
    if "{" in text or "}" in text:
        raise EquationLayoutError(f"nested raw text is unsupported in {label}.")
    return text, end


def _lex_manual(source: str) -> tuple[_Token, ...]:
    if not isinstance(source, str):
        raise TypeError("manual math source must be text.")
    if not source or not source.strip():
        raise EquationLayoutError("manual math source must not be empty.")
    if not source.isascii():
        raise EquationLayoutError("manual math source must remain ASCII TeX.")
    if any(character in source for character in "$<>&"):
        raise EquationLayoutError("manual math source contains raw markup or delimiters.")
    tokens: list[_Token] = []
    index = 0
    while index < len(source):
        character = source[index]
        if character.isspace():
            tokens.append(_Token("SPACE", "1", index))
            index += 1
            continue
        if character == "\\":
            start = index
            index += 1
            if index >= len(source):
                raise EquationLayoutError("manual TeX ends with a detached backslash.")
            if source[index].isalpha():
                end = index + 1
                while end < len(source) and source[end].isalpha():
                    end += 1
                command = source[index:end]
                index = end
            else:
                command = source[index]
                index += 1
            if command == "text":
                text, index = _raw_braced_text(source, index, "manual text")
                tokens.append(_Token("TEXT", text, start))
                continue
            token = _command_token(command, start)
            if token is not None:
                tokens.append(token)
            continue
        index = _lex_character(source, index, tokens)
    tokens.append(_Token("EOF", "", len(source)))
    return tuple(tokens)


def _replace_report_scripts(source: str) -> str:
    converted = source
    while True:
        match = _REPORT_SCRIPT_RE.search(converted)
        if match is None:
            break
        marker = "_" if match.group(1) == "sub" else "^"
        converted = converted[: match.start()] + marker + "{" + match.group(2) + "}" + converted[match.end() :]
    remaining_angles = converted.replace("->", "")
    if (
        _REPORT_TAG_RE.search(converted)
        or "<" in remaining_angles
        or ">" in remaining_angles
    ):
        raise EquationLayoutError("report math contains malformed or unsupported markup.")
    return converted


def _decode_report_entities(source: str) -> str:
    index = 0
    pieces: list[str] = []
    while index < len(source):
        if source[index] != "&":
            pieces.append(source[index])
            index += 1
            continue
        match = _REPORT_ENTITY_RE.match(source, index)
        if match is None:
            raise EquationLayoutError(
                f"report math contains an unsupported entity at position {index}."
            )
        decoded = html.unescape(match.group(0))
        pieces.append(" " if decoded == "\u00a0" else decoded)
        index = match.end()
    return "".join(pieces)


def _lex_report(source: str) -> tuple[_Token, ...]:
    if not isinstance(source, str):
        raise TypeError("report math source must be text.")
    if not source or not source.strip():
        raise EquationLayoutError("report math source must not be empty.")
    if not source.isascii():
        raise EquationLayoutError("report math source must remain ASCII markup.")
    if "\\" in source or "$" in source:
        raise EquationLayoutError("report math contains raw TeX.")
    converted = _replace_report_scripts(source)
    converted = _decode_report_entities(converted)
    tokens: list[_Token] = []
    index = 0
    while index < len(converted):
        if converted[index].isspace():
            tokens.append(_Token("SPACE", "1", index))
            index += 1
            continue
        index = _lex_character(converted, index, tokens, report=True)
    tokens.append(_Token("EOF", "", len(converted)))
    return tuple(tokens)


def _lex_character(
    source: str, index: int, tokens: list[_Token], *, report: bool = False
) -> int:
    character = source[index]
    single = {
        "{": "LBRACE",
        "}": "RBRACE",
        "(": "LPAREN",
        ")": "RPAREN",
        "[": "LBRACKET",
        "]": "RBRACKET",
        "_": "SUB",
        "^": "SUPER",
        "|": "BAR",
    }
    if character in single:
        tokens.append(_Token(single[character], character, index))
        return index + 1
    for candidate, displayed in (
        ("<=", _LE),
        (">=", _GE),
        ("!=", _NE),
        ("->", _ARROW),
    ):
        if source.startswith(candidate, index):
            tokens.append(_Token("OP", displayed, index))
            return index + len(candidate)
    if character in "+-=*/,:;.%<>":
        tokens.append(_Token("OP", character, index))
        return index + 1
    unicode_operators = {
        _LE,
        _GE,
        _NE,
        _TIMES,
        _DOT,
        _APPROX,
        _PLUS_MINUS,
        _ARROW,
    }
    if character in unicode_operators:
        tokens.append(_Token("OP", character, index))
        return index + 1
    if character in {_SUM, _DEGREE, _PER_MILLE, _INFINITY}:
        tokens.append(_Token("IDENT", character, index))
        return index + 1
    if character == _SQRT:
        tokens.append(_Token("ROOT", "report", index))
        return index + 1
    if character == _HALF:
        tokens.append(_Token("HALF", character, index))
        return index + 1
    if character == _OVERBAR:
        tokens.append(_Token("OVERBAR", character, index))
        return index + 1
    number = _NUMBER_RE.match(source, index)
    if number is not None:
        tokens.append(_Token("NUMBER", number.group(0), index))
        return number.end()
    if character.isalpha():
        end = index + 1
        while end < len(source) and source[end].isalnum():
            end += 1
        word = source[index:end]
        if report and word == "sqrt":
            tokens.append(_Token("ROOT", "report", index))
        else:
            tokens.append(_Token("IDENT", word, index))
        return end
    raise EquationLayoutError(
        f"unsupported mathematical character at position {index}: U+{ord(character):04X}."
    )


class _Parser:
    def __init__(self, tokens: tuple[_Token, ...]):
        self._tokens = tokens
        self._index = 0
        self._unit_identifier_indices: set[int] = set()

    @property
    def current(self) -> _Token:
        return self._tokens[self._index]

    def _advance(self) -> _Token:
        token = self.current
        self._index += 1
        return token

    def _skip_spaces(self) -> None:
        while self.current.kind == "SPACE":
            self._advance()

    def _previous_non_space_index(self, index: int) -> int | None:
        candidate = index - 1
        while candidate >= 0 and self._tokens[candidate].kind == "SPACE":
            candidate -= 1
        return candidate if candidate >= 0 else None

    def _next_non_space_index(self, index: int) -> int | None:
        candidate = index + 1
        while (
            candidate < len(self._tokens)
            and self._tokens[candidate].kind == "SPACE"
        ):
            candidate += 1
        return candidate if candidate < len(self._tokens) else None

    def _superscript_is_star(self, marker_index: int) -> bool:
        operand_index = self._next_non_space_index(marker_index)
        if operand_index is None:
            return False
        if self._tokens[operand_index].kind == "LBRACE":
            operand_index = self._next_non_space_index(operand_index)
            if operand_index is None:
                return False
        operand = self._tokens[operand_index]
        return operand.kind == "OP" and operand.value == "*"

    def _ambiguous_identifier_is_unit(self, index: int) -> bool:
        """Recognise N/m only in explicit numerical unit suffixes.

        Both letters are ordinary engineering quantity symbols throughout the
        governed corpus. They become units only after a numerical value, in a
        reciprocal such as ``1/m``, or as the continuation of an unambiguous
        unit product such as ``kN*m``. Semantic subscripts, ``N*`` and relation
        operands without a numerical unit context remain variables.
        """

        token = self._tokens[index]
        if token.value not in _AMBIGUOUS_UNIT_NAMES:
            return False

        next_index = self._next_non_space_index(index)
        if next_index is not None:
            following = self._tokens[next_index]
            if following.kind == "SUB":
                return False
            if following.kind == "SUPER" and self._superscript_is_star(next_index):
                return False

        previous_index = self._previous_non_space_index(index)
        if previous_index is None:
            return False
        previous = self._tokens[previous_index]
        if previous.kind == "NUMBER":
            return previous_index < index - 1
        if previous.kind == "IDENT":
            return (
                previous.value in _UNIT_NAMES - _AMBIGUOUS_UNIT_NAMES
                or previous_index in self._unit_identifier_indices
            )
        if previous.kind != "OP" or previous.value not in {
            "*",
            "/",
            _DOT,
            _TIMES,
        }:
            return False

        unit_left_index = self._previous_non_space_index(previous_index)
        if unit_left_index is None:
            return False
        unit_left = self._tokens[unit_left_index]
        if unit_left.kind == "IDENT":
            return (
                unit_left.value in _UNIT_NAMES - _AMBIGUOUS_UNIT_NAMES
                or unit_left_index in self._unit_identifier_indices
            )
        return (
            previous.value == "/"
            and token.value == "m"
            and unit_left.kind == "NUMBER"
            and unit_left.value == "1"
        )

    def parse(self) -> MathNode:
        self._skip_spaces()
        node = self._expression(0, frozenset(("EOF",)))
        self._skip_spaces()
        if self.current.kind != "EOF":
            raise EquationLayoutError(
                f"unexpected token at position {self.current.position}."
            )
        return node

    def parse_fragment(self) -> MathNode:
        """Parse complete math or an explicitly permitted leading relation."""

        self._skip_spaces()
        token = self.current
        if token.kind != "OP" or token.value not in _RELATIONS:
            return self.parse()
        self._advance()
        self._skip_spaces()
        if self.current.kind == "EOF":
            raise EquationLayoutError("a relation fragment has an empty right operand.")
        right = self._expression(0, frozenset(("EOF",)))
        self._skip_spaces()
        if self.current.kind != "EOF":
            raise EquationLayoutError(
                f"unexpected fragment token at position {self.current.position}."
            )
        return RelationFragment(Operator(token.value), right)

    def _expression(self, minimum: int, stops: frozenset[str]) -> MathNode:
        self._skip_spaces()
        if self.current.kind in stops:
            raise EquationLayoutError(
                f"empty mathematical operand at position {self.current.position}."
            )
        left = self._prefix(stops)
        postfix_percent = False
        while True:
            self._skip_spaces()
            token = self.current
            if token.kind in stops or token.kind == "EOF":
                break
            if token.kind == "OP" and token.value == "%":
                if postfix_percent:
                    raise EquationLayoutError(
                        f"duplicate postfix percent at position {token.position}."
                    )
                self._advance()
                left = math_sequence(left, Operator("%"))
                postfix_percent = True
                continue
            if token.kind == "OP" and token.value in _BINARY_PRECEDENCE:
                precedence = _BINARY_PRECEDENCE[token.value]
                if precedence < minimum:
                    break
                self._advance()
                self._skip_spaces()
                if self.current.kind in stops or self.current.kind == "EOF":
                    if token.value in {",", ";", "."}:
                        left = math_sequence(left, Operator(token.value))
                        break
                    raise EquationLayoutError(
                        f"operator {token.value!r} has an empty right operand."
                    )
                right = self._expression(precedence + 1, stops)
                left = self._binary(left, token.value, right)
                continue
            if self._starts_primary(token):
                precedence = 5
                if precedence < minimum:
                    break
                right = self._expression(precedence + 1, stops)
                if (
                    isinstance(left, Upright)
                    and left.text in _FUNCTION_NAMES
                    and isinstance(right, Delimited)
                ):
                    left = math_sequence(left, right)
                else:
                    left = math_sequence(left, MathSpace(), right)
                continue
            raise EquationLayoutError(
                f"unexpected token {token.value!r} at position {token.position}."
            )
        return left

    @staticmethod
    def _starts_primary(token: _Token) -> bool:
        return token.kind in {
            "IDENT",
            "NUMBER",
            "HALF",
            "FRAC",
            "ROOT",
            "TEXT",
            "ROMAN",
            "LPAREN",
            "LBRACKET",
            "LBRACE",
            "BAR",
        }

    def _prefix(self, stops: frozenset[str]) -> MathNode:
        token = self.current
        if token.kind == "OP" and token.value in {"+", "-", _PLUS_MINUS}:
            self._advance()
            operand = self._expression(6, stops)
            return math_sequence(Operator(token.value), operand)
        if token.kind == "IDENT":
            token_index = self._index
            ambiguous_unit = self._ambiguous_identifier_is_unit(token_index)
            self._advance()
            node = _identifier_node(token.value, ambiguous_unit=ambiguous_unit)
            if isinstance(node, Unit):
                self._unit_identifier_indices.add(token_index)
        elif token.kind == "NUMBER":
            self._advance()
            node = Number(token.value)
        elif token.kind == "HALF":
            self._advance()
            node = Fraction(Number("1"), Number("2"))
        elif token.kind == "TEXT":
            self._advance()
            node = Upright(token.value)
        elif token.kind == "FRAC":
            self._advance()
            numerator = self._required_group("fraction numerator")
            denominator = self._required_group("fraction denominator")
            node = Fraction(numerator, denominator)
        elif token.kind == "ROOT":
            self._advance()
            index = None
            self._skip_spaces()
            if token.value == "manual" and self.current.kind == "LBRACKET":
                index = self._delimited_group("LBRACKET", "RBRACKET", False)
            self._skip_spaces()
            if self.current.kind == "LBRACE":
                radicand = self._required_group("radical radicand")
            elif token.value == "report" and self.current.kind == "LBRACKET":
                radicand = self._delimited_group("LBRACKET", "RBRACKET", False)
            elif self.current.kind == "LPAREN":
                radicand = self._delimited_group("LPAREN", "RPAREN", False)
            elif token.value == "report" and self._starts_primary(self.current):
                radicand = self._prefix(stops)
            else:
                raise EquationLayoutError(
                    f"radical requires a grouped radicand at position {token.position}."
                )
            node = Radical(radicand, index)
        elif token.kind == "ROMAN":
            self._advance()
            node = _upright_tree(self._required_group("upright group"))
        elif token.kind == "LPAREN":
            node = self._delimited_group("LPAREN", "RPAREN", True)
        elif token.kind == "LBRACKET":
            node = self._delimited_group("LBRACKET", "RBRACKET", True)
        elif token.kind == "LBRACE":
            node = self._required_group("group")
        elif token.kind == "BAR":
            node = self._delimited_group("BAR", "BAR", True)
        elif token.kind in {"SUB", "SUPER"}:
            raise EquationLayoutError(
                f"detached script at position {token.position}."
            )
        else:
            raise EquationLayoutError(
                f"expected a mathematical operand at position {token.position}."
            )
        return self._scripts(node)

    def _scripts(self, base: MathNode) -> MathNode:
        self._skip_spaces()
        if self.current.kind == "OVERBAR":
            self._advance()
            base = Overbar(base)
        subscript = None
        superscript = None
        while True:
            self._skip_spaces()
            token = self.current
            if token.kind not in {"SUB", "SUPER"}:
                break
            self._advance()
            value = self._script_operand(token)
            if token.kind == "SUB":
                if subscript is not None:
                    raise EquationLayoutError("duplicate subscript on one base.")
                subscript = value
            else:
                if superscript is not None:
                    raise EquationLayoutError("duplicate superscript on one base.")
                superscript = value
        if subscript is None and superscript is None:
            return base
        return Script(base, subscript, superscript)

    def _script_operand(self, marker: _Token) -> MathNode:
        self._skip_spaces()
        if self.current.kind == "LBRACE":
            saved_index = self._index
            self._advance()
            self._skip_spaces()
            if self.current.kind == "OP" and self.current.value == "*":
                self._advance()
                self._skip_spaces()
                if self.current.kind != "RBRACE":
                    raise EquationLayoutError(
                        f"script at position {marker.position} has an invalid "
                        "operator operand."
                    )
                self._advance()
                return Operator("*")
            self._index = saved_index
            return self._required_group("script")
        if self.current.kind == "OP" and self.current.value == "*":
            self._advance()
            return Operator("*")
        if not self._starts_primary(self.current):
            raise EquationLayoutError(
                f"script at position {marker.position} has no operand."
            )
        return self._prefix(frozenset(("EOF",)))

    def _required_group(self, label: str) -> MathNode:
        self._skip_spaces()
        if self.current.kind != "LBRACE":
            raise EquationLayoutError(
                f"{label} requires braces at position {self.current.position}."
            )
        return self._delimited_group("LBRACE", "RBRACE", False)

    def _delimited_group(self, opening: str, closing: str, visible: bool) -> MathNode:
        token = self.current
        if token.kind != opening:
            raise EquationLayoutError(f"expected {opening} at position {token.position}.")
        self._advance()
        self._skip_spaces()
        if self.current.kind == closing:
            raise EquationLayoutError(
                f"empty delimited operand at position {token.position}."
            )
        content = self._expression(0, frozenset((closing,)))
        self._skip_spaces()
        if self.current.kind != closing:
            raise EquationLayoutError(
                f"unbalanced delimiter opened at position {token.position}."
            )
        self._advance()
        if not visible:
            return content
        delimiters = {
            "LPAREN": ("(", ")"),
            "LBRACKET": ("[", "]"),
            "BAR": ("|", "|"),
        }
        left, right = delimiters[opening]
        return Delimited(content, left, right)

    @staticmethod
    def _binary(left: MathNode, operator: str, right: MathNode) -> MathNode:
        if operator == "/":
            return Fraction(left, right)
        if operator in {",", ";", "."}:
            return math_sequence(left, Operator(operator), MathSpace(0.16), right)
        spacing = MathSpace(0.16 if operator == ":" else 0.24)
        return math_sequence(left, spacing, Operator(operator), spacing, right)


def _identifier_node(value: str, *, ambiguous_unit: bool = False) -> MathNode:
    if value in _GREEK_NAMES:
        return Variable(_GREEK_NAMES[value])
    if value == _SUM:
        return Operator(_SUM)
    if value in {_DEGREE, _PER_MILLE, _INFINITY}:
        return Operator(value)
    if value == "sum":
        return Operator(_SUM)
    if value == "permille":
        return Operator(_PER_MILLE)
    if value in _FUNCTION_NAMES:
        return Upright(value)
    if value in _AMBIGUOUS_UNIT_NAMES:
        return Unit(value) if ambiguous_unit else Variable(value)
    if value in _UNIT_NAMES:
        return Unit(value)
    if len(value) == 1 and value.isalpha():
        return Variable(value)
    return Upright(value)


def _upright_tree(node: MathNode) -> MathNode:
    if isinstance(node, Variable):
        return Upright(node.text)
    if isinstance(node, MathSequence):
        return MathSequence(tuple(_upright_tree(item) for item in node.items))
    if isinstance(node, Fraction):
        return Fraction(_upright_tree(node.numerator), _upright_tree(node.denominator))
    if isinstance(node, Radical):
        return Radical(
            _upright_tree(node.radicand),
            _upright_tree(node.index) if node.index is not None else None,
        )
    if isinstance(node, Script):
        return Script(
            _upright_tree(node.base),
            _upright_tree(node.subscript) if node.subscript is not None else None,
            _upright_tree(node.superscript) if node.superscript is not None else None,
        )
    if isinstance(node, Overbar):
        return Overbar(_upright_tree(node.base))
    if isinstance(node, RelationFragment):
        return RelationFragment(node.relation, _upright_tree(node.right))
    if isinstance(node, Delimited):
        return Delimited(_upright_tree(node.content), node.left, node.right)
    return node


def compile_manual_math(source: str) -> MathNode:
    """Compile the accepted manual TeX subset into a frozen display tree."""

    return _Parser(_lex_manual(source)).parse()


def compile_report_math(source: str) -> MathNode:
    """Compile the accepted report-markup subset into a frozen display tree."""

    return _Parser(_lex_report(source)).parse()


def compile_report_fragment(source: str) -> MathNode:
    """Compile substitution/result math, explicitly allowing a leading relation."""

    return _Parser(_lex_report(source)).parse_fragment()


def compile_report_literal(source: str) -> LiteralText:
    """Compile tightly validated upright result/verdict prose without markup."""

    if not isinstance(source, str):
        raise TypeError("report literal source must be text.")
    if not source or not source.strip():
        raise EquationLayoutError("report literal source must not be empty.")
    if not source.isascii():
        raise EquationLayoutError("report literal source must remain ASCII.")
    if "\\" in source or "$" in source or "{" in source or "}" in source:
        raise EquationLayoutError("report literal contains raw TeX or braces.")
    raw_angles = source.replace("->", "")
    if "<" in raw_angles or ">" in raw_angles:
        raise EquationLayoutError("report literal contains raw markup.")
    return LiteralText(_decode_report_entities(source).strip())


def _split_relation(
    node: MathNode,
) -> tuple[MathNode | None, Operator, MathNode] | None:
    if isinstance(node, RelationFragment):
        return None, node.relation, node.right
    if not isinstance(node, MathSequence):
        return None
    for index, item in enumerate(node.items):
        if isinstance(item, Operator) and item.text in _RELATIONS:
            left_items = _trim_items(node.items[:index])
            right_items = _trim_items(node.items[index + 1 :])
            if not left_items or not right_items:
                raise EquationLayoutError("a relation has an empty operand.")
            return (
                math_sequence(*left_items),
                item,
                math_sequence(*right_items),
            )
    return None


def _trim_items(items: tuple[MathNode, ...]) -> tuple[MathNode, ...]:
    start = 0
    end = len(items)
    while start < end and isinstance(items[start], MathSpace):
        start += 1
    while end > start and isinstance(items[end - 1], MathSpace):
        end -= 1
    return items[start:end]


def _break_groups(node: MathNode) -> tuple[MathNode, ...]:
    if not isinstance(node, MathSequence):
        return (node,)
    groups: list[MathNode] = []
    current: list[MathNode] = []
    for item in node.items:
        if isinstance(item, Operator) and item.text in _BREAK_OPERATORS and current:
            before = _trim_items(tuple(current))
            if before:
                groups.append(math_sequence(*before))
            current = [item]
        else:
            current.append(item)
        if isinstance(item, Operator) and item.text in {",", ";"}:
            complete = _trim_items(tuple(current))
            if complete:
                groups.append(math_sequence(*complete))
            current = []
    remaining = _trim_items(tuple(current))
    if remaining:
        groups.append(math_sequence(*remaining))
    return tuple(groups) or (node,)


def _wrap_math(
    node: MathNode, maximum_width: float, size: float, style: EquationStyle
) -> tuple[MathLayout, ...]:
    if maximum_width <= 0.0:
        raise EquationLayoutError("equation has no usable horizontal space.")
    whole = _layout_math(node, size, style)
    if whole.width <= maximum_width + 1e-7:
        return (whole,)
    if isinstance(node, LiteralText):
        words = node.text.split()
        literal_rows: list[MathLayout] = []
        literal_current = words[0]
        for word in words[1:]:
            candidate = LiteralText(literal_current + " " + word)
            candidate_layout = _layout_math(candidate, size, style)
            if candidate_layout.width <= maximum_width + 1e-7:
                literal_current = candidate.text
                continue
            current_layout = _layout_math(LiteralText(literal_current), size, style)
            if current_layout.width > maximum_width + 1e-7:
                raise EquationLayoutError(
                    "an unbreakable report-literal token exceeds the equation width."
                )
            literal_rows.append(current_layout)
            literal_current = word
        final = _layout_math(LiteralText(literal_current), size, style)
        if final.width > maximum_width + 1e-7:
            raise EquationLayoutError(
                "an unbreakable report-literal token exceeds the equation width."
            )
        literal_rows.append(final)
        return tuple(literal_rows)
    groups = _break_groups(node)
    if len(groups) == 1:
        raise EquationLayoutError(
            f"unbreakable equation atom is {whole.width:.2f} pt wide; "
            f"only {maximum_width:.2f} pt is available."
        )
    rows: list[MathLayout] = []
    current: MathNode | None = None
    for group in groups:
        group_layout = _layout_math(group, size, style)
        if group_layout.width > maximum_width + 1e-7:
            raise EquationLayoutError(
                f"unbreakable equation group is {group_layout.width:.2f} pt wide; "
                f"only {maximum_width:.2f} pt is available."
            )
        row_candidate = (
            group
            if current is None
            else math_sequence(current, MathSpace(), group)
        )
        candidate_layout = _layout_math(row_candidate, size, style)
        if current is not None and candidate_layout.width > maximum_width + 1e-7:
            rows.append(_layout_math(current, size, style))
            current = group
        else:
            current = row_candidate
    if current is not None:
        rows.append(_layout_math(current, size, style))
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class _RowPlan:
    role: str
    semantic: str
    layouts: tuple[MathLayout, ...]
    x_positions: tuple[float, ...]
    label: MathLayout | None
    relation_x: float | None
    separate_label_rows: tuple[MathLayout, ...] = ()
    math_offset: float = 0.0


def _plain_layout(
    text: str, size: float, style: EquationStyle, *, bold: bool, role: str, muted: bool
) -> MathLayout:
    return _text_layout(
        text,
        font_name=style.fonts.bold if bold else style.fonts.regular,
        font_size=size,
        slant=0.0,
        color=style.muted_ink if muted else style.ink,
        role=role,
        kind=role,
    )


def _aligned_metrics(layouts: tuple[MathLayout, ...]) -> tuple[float, float]:
    if not layouts:
        raise EquationLayoutError("aligned layout metrics require one layout.")
    baseline = max(layout.baseline for layout in layouts)
    ascent = max(layout.height - layout.baseline for layout in layouts)
    return baseline + ascent, baseline


def _wrap_plain_text(
    text: str, maximum_width: float, size: float, style: EquationStyle
) -> tuple[MathLayout, ...]:
    words = text.split()
    if not words:
        return ()
    rows: list[MathLayout] = []
    current = words[0]
    for word in words[1:]:
        candidate = current + " " + word
        layout = _plain_layout(
            candidate, size, style, bold=False, role="source", muted=True
        )
        if layout.width <= maximum_width + 1e-7:
            current = candidate
        else:
            row = _plain_layout(
                current, size, style, bold=False, role="source", muted=True
            )
            if row.width > maximum_width + 1e-7:
                raise EquationLayoutError("an unbreakable source token exceeds the equation width.")
            rows.append(row)
            current = word
    final = _plain_layout(
        current, size, style, bold=False, role="source", muted=True
    )
    if final.width > maximum_width + 1e-7:
        raise EquationLayoutError("an unbreakable source token exceeds the equation width.")
    rows.append(final)
    return tuple(rows)


def _wrap_label_text(
    text: str,
    maximum_width: float,
    size: float,
    style: EquationStyle,
    role: str,
) -> tuple[MathLayout, ...]:
    words = text.split()
    if not words:
        return ()
    rows: list[MathLayout] = []
    current = words[0]
    for word in words[1:]:
        candidate = current + " " + word
        layout = _plain_layout(
            candidate,
            size,
            style,
            bold=True,
            role=f"label-{role}",
            muted=False,
        )
        if layout.width <= maximum_width + 1e-7:
            current = candidate
            continue
        row = _plain_layout(
            current,
            size,
            style,
            bold=True,
            role=f"label-{role}",
            muted=False,
        )
        if row.width > maximum_width + 1e-7:
            raise EquationLayoutError(
                "an unbreakable equation-label token exceeds the frame width."
            )
        rows.append(row)
        current = word
    final = _plain_layout(
        current,
        size,
        style,
        bold=True,
        role=f"label-{role}",
        muted=False,
    )
    if final.width > maximum_width + 1e-7:
        raise EquationLayoutError(
            "an unbreakable equation-label token exceeds the frame width."
        )
    rows.append(final)
    return tuple(rows)


def _line_plans(
    block: EquationBlock,
    math_width: float,
    label_width: float,
    content_width: float,
    inline_math_offset: float,
    style: EquationStyle,
) -> tuple[_RowPlan, ...]:
    relations = [_split_relation(line.expression) for line in block.lines]
    left_layouts = [
        _layout_math(parts[0], style.font_size, style)
        if parts is not None and parts[0] is not None
        else None
        for parts in relations
    ]
    relation_layouts = [
        _layout_math(parts[1], style.font_size, style) if parts is not None else None
        for parts in relations
    ]
    relation_x = max(
        (layout.width for layout in left_layouts if layout is not None),
        default=0.0,
    )
    plans: list[_RowPlan] = []
    for line, parts, left, relation in zip(
        block.lines, relations, left_layouts, relation_layouts
    ):
        label = (
            _plain_layout(
                line.label,
                style.label_size,
                style,
                bold=True,
                role=f"label-{line.role}",
                muted=False,
            )
            if line.label is not None
            else None
        )
        separate_label_rows: tuple[MathLayout, ...] = ()
        if label is not None and label.width > label_width + 1e-7:
            assert line.label is not None
            separate_label_rows = _wrap_label_text(
                line.label,
                content_width,
                style.label_size,
                style,
                line.role,
            )
            label = None
        if parts is None:
            plan_math_width = (
                content_width if separate_label_rows else math_width
            )
            plan_math_offset = (
                0.0 if separate_label_rows else inline_math_offset
            )
            layouts = _wrap_math(
                line.expression,
                plan_math_width,
                style.font_size,
                style,
            )
            x_positions = tuple(0.0 for _layout in layouts)
            plans.append(
                _RowPlan(
                    line.role,
                    line.semantic_text or linear_math_text(line.expression),
                    layouts,
                    x_positions,
                    label,
                    None,
                    separate_label_rows,
                    plan_math_offset,
                )
            )
            continue
        assert relation is not None
        # A wrapped label sits above the equation, but it must not change the
        # shared relation axis.  All relation-bearing rows retain the common
        # mathematical column used by symbolic, substitution and result rows.
        plan_math_width = math_width
        plan_math_offset = inline_math_offset
        relation_gap = style.font_size * 0.24
        right_x = relation_x + relation.width + 2.0 * relation_gap
        right_width = plan_math_width - right_x
        if relation_x + relation.width > plan_math_width + 1e-7:
            raise EquationLayoutError("aligned relation leaves no usable equation width.")
        try:
            right_rows = _wrap_math(
                parts[2], right_width, style.font_size, style
            )
        except EquationLayoutError as aligned_error:
            # A long but otherwise valid right-hand atom (for example a
            # two-candidate min/max expression) may not fit after the shared
            # relation axis. Keep the aligned left operand and relation on the
            # first row, then hang the complete right operand below using the
            # full mathematical column. Unsupported or frame-wide atoms still
            # fail closed in the second _wrap_math call.
            hanging_offset = 0.0
            try:
                hanging_rows = _wrap_math(
                    parts[2], plan_math_width, style.font_size, style
                )
            except EquationLayoutError:
                try:
                    hanging_rows = _wrap_math(
                        parts[2], content_width, style.font_size, style
                    )
                except EquationLayoutError:
                    raise aligned_error
                # The first row keeps the shared relation axis.  A genuinely
                # oversized continuation may reclaim the label column below,
                # where no label is drawn.
                hanging_offset = -inline_math_offset
            aligned = tuple(
                layout
                for layout in (left, relation)
                if layout is not None
            )
            first_height, baseline = _aligned_metrics(aligned)
            moved_left = (
                _translate_layout(
                    left, relation_x - left.width, baseline - left.baseline
                )
                if left is not None
                else None
            )
            moved_relation = _translate_layout(
                relation,
                relation_x + relation_gap,
                baseline - relation.baseline,
            )
            first_layout = MathLayout(
                relation_x + relation_gap + relation.width,
                first_height,
                baseline,
                (
                    *(moved_left.texts if moved_left is not None else ()),
                    *moved_relation.texts,
                ),
                (
                    *(moved_left.rules if moved_left is not None else ()),
                    *moved_relation.rules,
                ),
                (
                    *(moved_left.nodes if moved_left is not None else ()),
                    *moved_relation.nodes,
                ),
            )
            plans.append(
                _RowPlan(
                    line.role,
                    line.semantic_text or linear_math_text(line.expression),
                    (first_layout, *hanging_rows),
                    (
                        0.0,
                        *(hanging_offset for _layout in hanging_rows),
                    ),
                    label,
                    relation_x + relation_gap,
                    separate_label_rows,
                    plan_math_offset,
                )
            )
            continue
        first = MathLayout(
            plan_math_width,
            max(
                left.height if left is not None else 0.0,
                relation.height,
                right_rows[0].height,
            ),
            max(
                left.baseline if left is not None else 0.0,
                relation.baseline,
                right_rows[0].baseline,
            ),
            (),
            (),
            (),
        )
        baseline = first.baseline
        moved_left = (
            _translate_layout(
                left, relation_x - left.width, baseline - left.baseline
            )
            if left is not None
            else None
        )
        moved_relation = _translate_layout(
            relation, relation_x + relation_gap, baseline - relation.baseline
        )
        first_right_x = relation_x + relation_gap + relation.width + relation_gap
        moved_right = _translate_layout(
            right_rows[0], first_right_x, baseline - right_rows[0].baseline
        )
        first_layout = MathLayout(
            max(
                relation_x,
                first_right_x + right_rows[0].width,
            ),
            first.height,
            baseline,
            (
                *(moved_left.texts if moved_left is not None else ()),
                *moved_relation.texts,
                *moved_right.texts,
            ),
            (
                *(moved_left.rules if moved_left is not None else ()),
                *moved_relation.rules,
                *moved_right.rules,
            ),
            (
                *(moved_left.nodes if moved_left is not None else ()),
                *moved_relation.nodes,
                *moved_right.nodes,
            ),
        )
        continuation_x = first_right_x
        continuation = tuple(right_rows[1:])
        layouts = (first_layout, *continuation)
        x_positions = (0.0, *(continuation_x for _layout in continuation))
        plans.append(
            _RowPlan(
                line.role,
                line.semantic_text or linear_math_text(line.expression),
                layouts,
                x_positions,
                label,
                relation_x + relation_gap,
                separate_label_rows,
                plan_math_offset,
            )
        )
    return tuple(plans)


def layout_equation(
    block: EquationBlock,
    available_width: float,
    *,
    style: EquationStyle = DEFAULT_EQUATION_STYLE,
    available_height: float | None = None,
) -> EquationGeometry:
    """Measure one aligned equation block, failing before any canvas mutation."""

    if type(block) is not EquationBlock:
        raise TypeError("layout_equation requires an exact EquationBlock value.")
    if not math.isfinite(available_width) or available_width <= 0.0:
        raise EquationLayoutError("available equation width must be finite and positive.")
    maximum_height = style.maximum_height if available_height is None else available_height
    if not math.isfinite(maximum_height) or maximum_height <= 0.0:
        raise EquationLayoutError("available equation height must be finite and positive.")
    content_width = available_width - style.left_indent - style.right_indent
    if content_width <= 0.0:
        raise EquationLayoutError("equation indents consume the available width.")
    labels = [
        _plain_layout(
            line.label,
            style.label_size,
            style,
            bold=True,
            role=f"label-{line.role}",
            muted=False,
        )
        for line in block.lines
        if line.label is not None
    ]
    maximum_label_width = max((label.width for label in labels), default=0.0)
    label_width = min(maximum_label_width, content_width * 0.34)
    math_x = style.left_indent + (label_width + style.label_gap if labels else 0.0)
    math_width = available_width - style.right_indent - math_x
    if math_width <= style.font_size:
        raise EquationLayoutError("equation labels leave no usable mathematical width.")
    plans = _line_plans(
        block,
        math_width,
        label_width,
        content_width,
        math_x - style.left_indent,
        style,
    )
    identity = (
        _plain_layout(
            block.identity,
            style.identity_size,
            style,
            bold=True,
            role="identity",
            muted=False,
        )
        if block.identity is not None
        else None
    )
    identity_separate = False
    if identity is not None:
        first_plan = plans[0]
        first_right = max(
            (
                x + layout.width
                for x, layout in zip(first_plan.x_positions, first_plan.layouts)
            ),
            default=0.0,
        )
        identity_separate = (
            style.left_indent
            + plans[0].math_offset
            + first_right
            + style.identity_gap
            + identity.width
            > available_width - style.right_indent
        )
        if identity.width > content_width + 1e-7:
            raise EquationLayoutError("equation identity is wider than the publication frame.")
    source_rows = (
        _wrap_plain_text(block.source, content_width, style.source_size, style)
        if block.source is not None
        else ()
    )

    item_heights: list[tuple[str, float, object]] = []
    if identity is not None and identity_separate:
        item_heights.append(("identity", identity.height, identity))
    for plan_index, plan in enumerate(plans):
        for label_row in plan.separate_label_rows:
            item_heights.append(("line-label", label_row.height, label_row))
        for index, layout in enumerate(plan.layouts):
            label = plan.label if index == 0 else None
            inline_identity = (
                identity is not None
                and not identity_separate
                and plan_index == 0
                and index == 0
            )
            aligned = (
                layout,
                *((label,) if label is not None else ()),
                *((identity,) if inline_identity and identity is not None else ()),
            )
            row_height, _baseline = _aligned_metrics(aligned)
            item_heights.append(
                ("math", row_height, (plan, index, label, inline_identity))
            )
    if source_rows:
        item_heights.append(("source-gap", style.source_gap, None))
        for row in source_rows:
            item_heights.append(("source", row.height, row))

    gaps = style.row_gap * max(0, len(item_heights) - 1)
    height = (
        style.top_padding
        + style.bottom_padding
        + sum(item[1] for item in item_heights)
        + gaps
    )
    if height > maximum_height + 1e-7:
        raise EquationLayoutError(
            f"equation block is {height:.2f} pt high; only {maximum_height:.2f} pt is allowed."
        )
    texts: list[TextPlacement] = []
    rules: list[RulePlacement] = []
    nodes: list[NodePlacement] = []
    rows: list[EquationRowLayout] = []
    semantic_texts: list[TextPlacement] = []
    cursor_top = height - style.top_padding
    first_math_y: float | None = None
    for kind, item_height, payload in item_heights:
        y = cursor_top - item_height
        if kind == "identity":
            assert isinstance(payload, MathLayout)
            moved = _translate_layout(
                payload,
                available_width - style.right_indent - payload.width,
                y + item_height - payload.height,
            )
            texts.extend(moved.texts)
            nodes.extend(moved.nodes)
        elif kind == "line-label":
            assert isinstance(payload, MathLayout)
            moved = _translate_layout(payload, style.left_indent, y)
            texts.extend(moved.texts)
            rules.extend(moved.rules)
            nodes.extend(moved.nodes)
        elif kind == "math":
            assert isinstance(payload, tuple)
            plan, index, label, inline_identity = payload
            assert isinstance(plan, _RowPlan) and isinstance(index, int)
            assert isinstance(inline_identity, bool)
            math_layout = plan.layouts[index]
            aligned = (
                math_layout,
                *((label,) if isinstance(label, MathLayout) else ()),
                *((identity,) if inline_identity and identity is not None else ()),
            )
            _row_height, baseline = _aligned_metrics(aligned)
            math_y = y + baseline - math_layout.baseline
            math_dx = (
                style.left_indent
                + plan.math_offset
                + plan.x_positions[index]
            )
            moved_math = _translate_layout(math_layout, math_dx, math_y)
            texts.extend(moved_math.texts)
            rules.extend(moved_math.rules)
            nodes.extend(moved_math.nodes)
            if isinstance(label, MathLayout):
                moved_label = _translate_layout(
                    label,
                    style.left_indent,
                    y + baseline - label.baseline,
                )
                texts.extend(moved_label.texts)
                nodes.extend(moved_label.nodes)
            if first_math_y is None:
                first_math_y = y + baseline
            if index == 0:
                semantic = (
                    f"SECTOR-MATH[{plan.role}] "
                    + plan.semantic
                )
                _require_glyphs(style.fonts.regular, semantic)
                semantic_width = pdfmetrics.stringWidth(
                    semantic, style.fonts.regular, 1.0
                )
                semantic_size = (
                    min(1.0, content_width / semantic_width)
                    if semantic_width > 0.0
                    else 1.0
                )
                semantic_texts.append(
                    TextPlacement(
                        semantic,
                        style.left_indent,
                        y + baseline,
                        style.fonts.regular,
                        semantic_size,
                        0.0,
                        style.ink,
                        f"semantic-{plan.role}",
                        3,
                    )
                )
            rows.append(
                EquationRowLayout(
                    plan.role,
                    Bounds(
                        style.left_indent,
                        y,
                        available_width - style.left_indent - style.right_indent,
                        item_height,
                    ),
                    style.left_indent + plan.math_offset + plan.relation_x
                    if plan.relation_x is not None and index == 0
                    else None,
                    index > 0,
                )
            )
        elif kind == "source":
            assert isinstance(payload, MathLayout)
            moved = _translate_layout(payload, style.left_indent, y)
            texts.extend(moved.texts)
            nodes.extend(moved.nodes)
        cursor_top = y - style.row_gap

    if identity is not None and not identity_separate:
        assert first_math_y is not None
        moved_identity = _translate_layout(
            identity,
            available_width - style.right_indent - identity.width,
            first_math_y - identity.baseline,
        )
        texts = [*moved_identity.texts, *texts]
        nodes.extend(moved_identity.nodes)
    texts = [*semantic_texts, *texts]
    nodes.append(NodePlacement("equation-block", Bounds(0.0, 0.0, available_width, height)))
    return EquationGeometry(
        available_width,
        height,
        tuple(texts),
        tuple(rules),
        tuple(nodes),
        tuple(rows),
    )


def _draw_text(canvas: Canvas, placement: TextPlacement) -> None:
    canvas.saveState()
    canvas.setFillColor(colors.HexColor(placement.color))
    text = canvas.beginText()
    text.setFont(placement.font_name, placement.font_size)
    text.setTextRenderMode(placement.render_mode)
    text.setTextTransform(
        1.0,
        0.0,
        placement.slant,
        1.0,
        placement.x,
        placement.baseline,
    )
    text.textOut(placement.text)
    canvas.drawText(text)
    canvas.restoreState()


class EquationFlowable(Flowable):
    """One indivisible aligned equation block with searchable vector output."""

    def __init__(
        self,
        block: EquationBlock,
        *,
        style: EquationStyle = DEFAULT_EQUATION_STYLE,
    ) -> None:
        if type(block) is not EquationBlock:
            raise TypeError("EquationFlowable requires an exact EquationBlock value.")
        if type(style) is not EquationStyle:
            raise TypeError("EquationFlowable requires an exact EquationStyle value.")
        super().__init__()
        self.block = block
        self.style = style
        self._equation_geometry: EquationGeometry | None = None

    @property
    def geometry(self) -> EquationGeometry:
        if self._equation_geometry is None:
            raise EquationLayoutError("equation geometry is unavailable before wrap().")
        return self._equation_geometry

    def getPlainText(self) -> str:
        parts: list[str] = []
        if self.block.identity is not None:
            parts.append(self.block.identity)
        for line in self.block.lines:
            if line.semantic_text is not None:
                parts.append(line.semantic_text)
                continue
            prefix = f"{line.label} " if line.label is not None else ""
            parts.append(prefix + linear_math_text(line.expression))
        if self.block.source is not None:
            parts.append(self.block.source)
        return " ".join(parts)

    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:
        del availHeight
        geometry = layout_equation(
            self.block,
            availWidth,
            style=self.style,
            available_height=self.style.maximum_height,
        )
        self._equation_geometry = geometry
        self.width = geometry.width
        self.height = geometry.height
        return geometry.width, geometry.height

    def split(self, availWidth: float, availHeight: float) -> list[Flowable]:
        del availWidth, availHeight
        return []

    def draw(self) -> None:
        geometry = self.geometry
        canvas = self.canv
        for placement in geometry.texts:
            _draw_text(canvas, placement)
        for rule in geometry.rules:
            canvas.saveState()
            canvas.setStrokeColor(colors.HexColor(rule.color))
            canvas.setLineWidth(rule.thickness)
            canvas.line(rule.x1, rule.y1, rule.x2, rule.y2)
            canvas.restoreState()


__all__ = (
    "DEFAULT_EQUATION_STYLE",
    "Bounds",
    "Delimited",
    "EquationBlock",
    "EquationFlowable",
    "EquationFontError",
    "EquationFonts",
    "EquationGeometry",
    "EquationLayoutError",
    "EquationLine",
    "EquationRowLayout",
    "EquationStyle",
    "Fraction",
    "LiteralText",
    "MathLayout",
    "MathNode",
    "MathSequence",
    "MathSpace",
    "NodePlacement",
    "Number",
    "Operator",
    "Overbar",
    "Radical",
    "RelationFragment",
    "RulePlacement",
    "Script",
    "TextPlacement",
    "Unit",
    "Upright",
    "Variable",
    "compile_manual_math",
    "compile_report_fragment",
    "compile_report_literal",
    "compile_report_math",
    "layout_equation",
    "layout_math",
    "linear_math_text",
    "math_sequence",
    "register_default_equation_fonts",
)
