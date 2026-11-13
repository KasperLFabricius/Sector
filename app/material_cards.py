"""Material cards: the values of each material law beside its curve.

A card reads each value from the material object or the entered value that the
calculation uses. It adds no formula of its own. Each row names the clause of
the edition that the material preset selects. A preset without an edition (a
Sector curve law) gives no clause.

A card holds one material. ``card_markdown`` renders one or more cards, so a
page can show several materials of one kind together.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from sector import capacity, codes

PERMILLE = "\u2030"
DEGREE = "\u00b0"
_NBSP = "\u00a0"  # keeps a value and its unit on one line
CONDITION = f"20 {DEGREE}C, concrete age 28 days, persistent design situation"
STEEL_CONDITION = f"20 {DEGREE}C, persistent design situation"

_EDITION_2004 = "EC2-2005"
_EDITION_DK_NA = "EC2-2005-DKNA2024"
_EDITION_2023 = "EC2-2023"


@dataclass(frozen=True)
class CardRow:
    """One design value: LaTeX symbol, formatted value and its basis."""

    quantity: str
    value: str
    basis: str


@dataclass(frozen=True)
class MaterialCard:
    """The design values of one material and the condition they apply to."""

    title: str
    edition: str
    condition: str
    rows: tuple[CardRow, ...]
    notes: tuple[str, ...] = ()


def edition_key(preset: object) -> str | None:
    """Return the code key of an edition preset, or None for a curve preset."""
    code = codes.CODES.get(str(preset))
    return None if code is None else str(code.key)


def _edition_text(preset: object) -> str:
    if edition_key(preset) is None:
        return f"{preset} (Sector curve law, no standard clause)"
    return str(preset)


def _basis(*parts: str | None) -> str:
    return "; ".join(part for part in parts if part)


def _clause(key: str | None, by_edition: dict[str, str]) -> str | None:
    return None if key is None else by_edition[key]


def horizontal_top_branch(steel) -> bool:
    """Return True when the design law of a bar has a horizontal top branch.

    Curve 2 is elastic-perfectly plastic. Curves 1 and 3 are horizontal at the
    top when the design ultimate stress futk/gamma_u equals the design yield
    stress fytk/gamma_y (the edition presets).
    """
    if steel.curve == 2:
        return True
    return math.isclose(steel.futk / steel.gamma_u, steel.fytk / steel.gamma_y,
                        rel_tol=1.0e-9)


def _mpa(value: float) -> str:
    return f"{value:.2f}{_NBSP}MPa"


def _gpa(value: float) -> str:
    return f"{value:.1f}{_NBSP}GPa"


def _permille(value: float) -> str:
    return f"{value * 1000.0:.2f}{_NBSP}{PERMILLE}"


def concrete_card(concrete, *, fctm_mpa: float, ec_gpa: float,
                  preset: object, title: str = "Concrete") -> MaterialCard:
    """Card of the concrete law and the entered fctm and Ec of the calculation.

    ``concrete`` is the :class:`sector.materials.Concrete` of the calculation.
    ``fctm_mpa`` and ``ec_gpa`` are the entered values that the elastic,
    crack-width and minimum-reinforcement calculations use. The reference
    values of EN 1992-1-1:2004 Table 3.1 are the values of the Auto buttons.
    """
    key = edition_key(preset)
    fck = float(concrete.fck)
    # The Auto buttons use EN 1992-1-1:2004 Table 3.1 for every preset.
    table = "EN 1992-1-1:2004 Table 3.1"
    fcd_formula = (r"$\eta_{cc}k_{tc}f_{ck}/\gamma_C$" if key == _EDITION_2023
                   else r"$\alpha_{cc}f_{ck}/\gamma_c$")
    strain_clause = {
        _EDITION_2004: "Table 3.1, 3.1.7(1)",
        _EDITION_DK_NA: "Table 3.1, 3.1.7(1)",
        _EDITION_2023: "8.1.2(1), (8.4)",
    }
    # DS/EN 1992-1-1:2023 8.1.2(1) names the ultimate strain eps_cu.
    ultimate = (r"$\varepsilon_{cu}$" if key == _EDITION_2023
                else r"$\varepsilon_{cu2}$")
    rows = (
        CardRow(r"$f_{cd}$", _mpa(concrete.fcd), _basis(
            fcd_formula,
            _clause(key, {
                _EDITION_2004: r"3.1.6(1)P, (3.15); $\gamma_c$: Table 2.1N",
                _EDITION_DK_NA: r"3.1.6(1)P, (3.15); $\gamma_c$: DK NA "
                                "Table 2.1Na NA",
                _EDITION_2023: r"5.1.6(1), (5.3), (5.4); $\gamma_C$: Table 4.3",
            }),
        )),
        CardRow(r"$f_{ctm}$", _mpa(fctm_mpa), _basis(
            "Entered", f"{table}: {_mpa(codes.fctm(fck))}",
        )),
        CardRow(r"$E_c$", _gpa(ec_gpa), _basis(
            "Entered", f"{table}, $E_{{cm}}$: {_gpa(codes.ecm(fck) / 1000.0)}",
        )),
        CardRow(r"$\varepsilon_{c2}$", _permille(concrete.eps_c2),
                _basis(_clause(key, strain_clause)) or "-"),
        CardRow(ultimate, _permille(concrete.eps_cu2),
                _basis(_clause(key, strain_clause)) or "-"),
    )
    notes = ((
        "The cracking, crack-width and minimum-reinforcement calculations use "
        r"the entered $f_{ctm}$. The torsion cracking resistance uses "
        r"$f_{ctk,0.05}=0.7f_{ctm}$ with $f_{ctm}$ of EN 1992-1-1:2004 "
        r"Table 3.1. The modular ratios and the decompression strain of "
        r"bonded tendons use the entered $E_c$."
    ),)
    return MaterialCard(title, _edition_text(preset), CONDITION, rows, notes)


def reinforcing_steel_card(steel, *, preset: object,
                           title: str = "Reinforcing steel") -> MaterialCard:
    """Card of one reinforcing-steel law of the calculation.

    The strain-limit clause follows the top branch of the law: a horizontal
    branch is method b) without a strain limit, an inclined branch is method
    a) with eps_ud. The entered rupture strain is the limit of the plastic
    analysis in both cases.
    """
    key = edition_key(preset)
    if horizontal_top_branch(steel):
        strain_clause = {
            _EDITION_2004: "3.2.7(2) b): no strain limit",
            _EDITION_DK_NA: "DK NA 3.2.7(2): method b), no strain limit",
            _EDITION_2023: "5.2.4(2) b): no strain limit",
        }
    else:
        strain_clause = {
            _EDITION_2004: r"3.2.7(2) a), Note 1: $0.9\varepsilon_{uk}$",
            _EDITION_DK_NA: r"3.2.7(2) a); DK NA 3.2.7(2) selects method b)",
            _EDITION_2023: r"5.2.4(2) a): "
                           r"$\varepsilon_{ud}\le\varepsilon_{uk}/\gamma_S$",
        }
    rows = (
        CardRow(r"$f_{yd}$", _mpa(capacity.design_yield(steel)), _basis(
            r"$f_{ytk}/\gamma_y$",
            _clause(key, {
                _EDITION_2004: r"3.2.7(2), Figure 3.8; $\gamma_s$: Table 2.1N",
                _EDITION_DK_NA: r"3.2.7(2), Figure 3.8; $\gamma_s$: DK NA "
                                "Table 2.1Na NA",
                _EDITION_2023: r"5.2.4(1), (5.11); $\gamma_S$: Table 4.3",
            }),
        )),
        CardRow(r"$\varepsilon_{ud}$", _permille(steel.eut), _basis(
            r"Entered $\varepsilon_{ut}$", _clause(key, strain_clause),
        )),
        CardRow("Compression", "active" if (
            steel.active_in_compression and steel.fyck > 0.0) else "tension only",
            "-"),
    )
    notes = (
        r"The plastic analysis limits the bar strain to $\varepsilon_{ud}$.",
    )
    return MaterialCard(title, _edition_text(preset), STEEL_CONDITION, rows,
                        notes)


def prestressing_steel_card(prestress, *, preset: object,
                            title: str = "Prestressing steel") -> MaterialCard:
    """Card of one prestressing-steel law of the calculation."""
    key = edition_key(preset)
    if prestress.curve in (6, 7):
        fpd = CardRow(r"$f_{pd}$", _mpa(capacity.design_yield(prestress)),
                      _basis(r"$f_{p0.1k}/\gamma_y$", _clause(key, {
                          _EDITION_2004: r"3.3.6(6); $\gamma_s$: Table 2.1N",
                          _EDITION_DK_NA: r"3.3.6(6); $\gamma_s$: DK NA "
                                          "Table 2.1Na NA",
                          _EDITION_2023: r"5.3.3(1), (5.12); $\gamma_S$: "
                                         "Table 4.3",
                      })))
    else:
        fpd = CardRow(r"$f_{pd}$", "-",
                      f"Built-in curve {prestress.curve}: fixed law")
    strain = prestress.rupture_strain
    if prestress.curve in (6, 7):
        # The law reaches fpk/gamma_u at eut, so eut is eps_uk of the clauses.
        # The clause values are references only (owner question Q4).
        source = r"Entered $\varepsilon_{ut}$, total tendon strain"
        reference = _clause(key, {
            _EDITION_2004: r"3.3.6(7), Note: $0.9\varepsilon_{uk}$ = "
                           + _permille(0.9 * strain),
            _EDITION_DK_NA: r"3.3.6(7), Note: $0.9\varepsilon_{uk}$ = "
                            + _permille(0.9 * strain),
            _EDITION_2023: r"5.3.3(2) a): $\varepsilon_{uk}/\gamma_S$ = "
                           + _permille(strain / prestress.gamma_u),
        })
    else:
        source = f"Built-in curve {prestress.curve}: fixed rupture strain"
        reference = None
    rows = (
        fpd,
        CardRow(r"$\varepsilon_{ud}$", _permille(strain),
                _basis(source, reference)),
    )
    notes = ((
        "The plastic analysis limits the total tendon strain to "
        r"$\varepsilon_{ud}$."
    ),)
    return MaterialCard(title, _edition_text(preset), STEEL_CONDITION, rows,
                        notes)


def card_markdown(cards: MaterialCard | Iterable[MaterialCard]) -> str:
    """Render one or more cards as Markdown tables with their titles."""
    if isinstance(cards, MaterialCard):
        cards = (cards,)
    blocks = []
    for card in cards:
        blocks.append("\n".join((
            f"**Material values: {card.title}**",
            "",
            "| Quantity | Value | Basis |",
            "|---|---|---|",
            *(f"| {row.quantity} | {row.value} | {row.basis} |"
              for row in card.rows),
        )))
    return "\n\n".join(blocks)


def card_caption(card: MaterialCard) -> str:
    """The edition, the condition and the notes of one card."""
    return " ".join((
        f"Edition: {card.edition}. Condition: {card.condition}.",
        *card.notes,
    ))
