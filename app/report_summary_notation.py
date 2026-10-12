"""Report-only notation with a separate, unchanged plain-text value.

Only source-authored chunks enter ``authored``. Interpolated identities and
descriptions enter ``field`` and remain literal unless they already carry
validated fragments. The renderer never scans a completed result string.
"""

import re
from string import Formatter
from types import MappingProxyType


CATALOGUE = MappingProxyType({
    "fyk": "f<sub>yk</sub>", "fywk": "f<sub>ywk</sub>",
    "u_k": "u<sub>k</sub>", "z_x": "z<sub>x</sub>", "z_y": "z<sub>y</sub>",
    "As,req": "A<sub>s,req</sub>", "As,prov": "A<sub>s,prov</sub>",
    "As,min": "A<sub>s,min</sub>", "Rnom": "R<sub>nom</sub>",
    "Rcr": "R<sub>cr</sub>", "MR,nom": "M<sub>R,nom</sub>",
    "Mcr": "M<sub>cr</sub>", "sprov": "s<sub>prov</sub>",
    "smax": "s<sub>max</sub>",
    "\u03c1w,prov": "&#961;<sub>w,prov</sub>",
    "\u03c1w,min": "&#961;<sub>w,min</sub>",
    "VRd,c": "V<sub>Rd,c</sub>", "V_Rd,c": "V<sub>Rd,c</sub>",
    "VRd,s": "V<sub>Rd,s</sub>", "VRd,max": "V<sub>Rd,max</sub>",
    "V_Rd,s": "V<sub>Rd,s</sub>", "V_Rd,max": "V<sub>Rd,max</sub>",
    "Asw": "A<sub>sw</sub>", "bw": "b<sub>w</sub>",
    "VEd": "V<sub>Ed</sub>", "Vx,Ed": "V<sub>x,Ed</sub>",
    "Vy,Ed": "V<sub>y,Ed</sub>", "TEd": "T<sub>Ed</sub>",
    "N_Ed": "N<sub>Ed</sub>", "M_Ed": "M<sub>Ed</sub>",
    "T_Rd,c": "T<sub>Rd,c</sub>", "TRd,c": "T<sub>Rd,c</sub>",
    "TRd,s": "T<sub>Rd,s</sub>", "TRd,max": "T<sub>Rd,max</sub>",
    "w_k": "w<sub>k</sub>", "w_k,criterion": "w<sub>k,criterion</sub>",
    "lambda_cr": "&#955;<sub>cr</sub>",
    "f_ck": "f<sub>ck</sub>", "f_yk": "f<sub>yk</sub>",
    "f_pk": "f<sub>pk</sub>", "f_p0.1k": "f<sub>p0.1k</sub>",
    "mm2": "mm<super>2</super>", "mm3": "mm<super>3</super>",
    "m2": "m<super>2</super>", "m3": "m<super>3</super>",
    "m4": "m<super>4</super>",
})
_TOKEN = re.compile(r"(?<![A-Za-z0-9_])(?:" + "|".join(
    re.escape(key) for key in sorted(CATALOGUE, key=len, reverse=True)
) + r")(?![A-Za-z0-9_])|; ")

_SCIENTIFIC = re.compile(r"([+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+))[eE]([+-]?[0-9]+)")


def valid_fragments(value, fragments):
    """Fail closed if fragments are absent, invalid, or for a replaced field."""
    if not isinstance(fragments, (tuple, list)):
        return False
    for item in fragments:
        if (not isinstance(item, (tuple, list)) or len(item) != 2
                or not isinstance(item[0], str)
                or item[0] not in {"literal", "catalogue", "scientific", "clause"}
                or not isinstance(item[1], str)
                or (item[0] == "clause" and item[1] != "; ")
                or (item[0] == "catalogue" and item[1] not in CATALOGUE)
                or (item[0] == "scientific" and not _SCIENTIFIC.fullmatch(item[1]))):
            return False
    return "".join(item[1] for item in fragments) == value


class ReportText(str):
    """A plain string with optional fragments for internal text assembly."""

    def __new__(cls, value, fragments=()):
        obj = super().__new__(cls, value)
        obj.fragments = tuple(tuple(item) for item in fragments)
        return obj

    def __add__(self, other):
        if not isinstance(other, str):
            return NotImplemented
        return concat(self, other)

    def __radd__(self, other):
        if not isinstance(other, str):
            return NotImplemented
        return concat(other, self)

    def strip(self, chars=None):
        return _trim(self, str.strip(self, chars))

    def rstrip(self, chars=None):
        return _trim(self, str.rstrip(self, chars), right_only=True)


def _fragments(value):
    if isinstance(value, ReportText) and valid_fragments(value, value.fragments):
        return value.fragments
    return (("literal", str(value)),)


def _trim(value, result, right_only=False):
    start = 0 if right_only else str(value).find(result)
    end = start + len(result)
    pieces = []
    position = 0
    for kind, plain in _fragments(value):
        left, right = max(start - position, 0), min(end - position, len(plain))
        if left < right:
            kept = plain[left:right]
            pieces.append((kind if kept == plain else "literal", kept))
        position += len(plain)
    return ReportText(result, pieces)


def authored(value):
    """Mark only catalogue tokens within a source-authored constant chunk."""
    fragments = []
    offset = 0
    for match in _TOKEN.finditer(value):
        fragments.extend((("literal", value[offset:match.start()]),
                          ("clause" if match.group() == "; " else "catalogue", match.group())))
        offset = match.end()
    fragments.append(("literal", value[offset:]))
    return ReportText(value, fragments)


def symbol(value):
    """Use an exact controlled symbol key; unknown labels remain literal."""
    return ReportText(value, (("catalogue" if value in CATALOGUE else "literal", value),))


def number(plain):
    """Mark one already-formatted native number; retain its exact plain text."""
    kind = "scientific" if _SCIENTIFIC.fullmatch(plain) else "literal"
    return ReportText(plain, ((kind, plain),))


def field(value, conversion=None, spec=""):
    """Keep an f-string's formatting, with literal provenance for its inputs."""
    if conversion is None and spec == "" and isinstance(value, ReportText):
        return value
    if conversion == "r":
        value = repr(value)
    elif conversion == "s":
        value = str(value)
    elif conversion == "a":
        value = ascii(value)
    return format(value, spec)


def text(template, *values):
    """Format an authored template; keep each substituted value literal.

    Templates use anonymous fields, with ordinary Python format specifications.
    An existing ReportText value retains its fragments when no conversion or
    format specification is present.
    """
    parts = []
    index = 0
    for chunk, name, spec, conversion in Formatter().parse(template):
        parts.append(authored(chunk))
        if name is not None:
            if name != "":
                raise ValueError("Report templates require anonymous fields")
            parts.append(field(values[index], conversion, spec))
            index += 1
    if index != len(values):
        raise ValueError("Report template and value counts differ")
    return concat(*parts)


def concat(*values):
    fragments = tuple(piece for value in values for piece in _fragments(value))
    return ReportText("".join(str(value) for value in values), fragments)


def join(separator, values):
    values = list(values)
    if any(not isinstance(value, str) for value in values):
        # Retain native str.join failure behavior.
        separator.join(values)
    parts = []
    for index, value in enumerate(values):
        if index:
            parts.append(authored(separator))
        parts.append(value)
    return concat(*parts)


def attach(row):
    """Store plain shared fields and optional report-only fragment metadata."""
    fields = {}
    for name, value in row.items():
        if isinstance(value, ReportText):
            if (name in {"result", "criterion", "note"}
                    and valid_fragments(value, value.fragments)
                    and any(kind != "literal" for kind, _ in value.fragments)):
                fields[name] = value.fragments
            row[name] = str(value)
    if fields:
        row["report_fields"] = fields
    return row


def row_field(row, name):
    value = row.get(name, "")
    metadata = row.get("report_fields")
    fragments = metadata.get(name) if isinstance(metadata, dict) else None
    return (ReportText(value, fragments) if valid_fragments(value, fragments)
            else value)


def render(value, escape):
    """Render closed catalogue markup and shield all remaining characters."""
    parts = []
    for kind, plain in _fragments(value):
        if kind == "catalogue":
            parts.append(CATALOGUE[plain])
        elif kind == "scientific":
            mantissa, exponent = _SCIENTIFIC.fullmatch(plain).groups()
            # Preserve every mantissa digit. Only the exponent's leading zeros
            # and optional positive sign are removed from the display.
            parts.append(escape(mantissa) + " &#215; 10<super>"
                         + str(int(exponent)) + "</super>")
        else:
            parts.append(escape(plain))
    return "".join(parts)


_NATIVE_SCOPE_TEXT = frozenset({
    "Ordinary reinforcement is assumed anchored to develop the entered fyk; reduce fyk where it cannot.",
    "The nominal resistance uses the entered design concrete law and limits every mild bar to its characteristic fyk.",
    "Stirrup anchorage is assumed. Reduce fywk when full anchorage is not available.",
})


def native_scope(value):
    """Format only exact native scope strings; retain unknown text literally."""
    return authored(value) if type(value) is str and value in _NATIVE_SCOPE_TEXT else value


def note_parts(value):
    """Break a note only at source-authored clause delimiters.

    The returned strings retain every character and fragment. Unknown text,
    user fields and stale metadata retain their original paragraph.
    """
    parts, pieces = [], []
    for kind, plain in _fragments(value):
        pieces.append((kind, plain))
        if kind == "clause":
            parts.append(ReportText("".join(p for _, p in pieces), pieces))
            pieces = []
    if pieces:
        parts.append(ReportText("".join(p for _, p in pieces), pieces))
    return tuple(parts) or (value,)
