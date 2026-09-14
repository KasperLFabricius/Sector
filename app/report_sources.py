"""User-supplied publication references, independent of calculation authority."""

from __future__ import annotations

from collections.abc import Mapping

KEY = "rep_source_register"
SCOPES = ("Project", "Plastic", "Elastic", "Fatigue")
FIELDS = frozenset({"scope", "case_name", "document", "locator"})


def validate(value: object) -> list[dict[str, str]]:
    """Copy an exact optional register; incomplete references remain publishable."""
    if type(value) is not list:
        raise ValueError(f"{KEY} must be a list")
    result = []
    identities = set()
    for entry in value:
        if type(entry) is not dict or set(entry) != FIELDS:
            raise ValueError(f"{KEY} entries must contain scope, case_name, document and locator")
        if any(type(item) is not str for item in entry.values()):
            raise ValueError(f"{KEY} entry fields must be text")
        scope, name = entry["scope"], entry["case_name"]
        if scope not in SCOPES:
            raise ValueError(f"{KEY} has an unknown scope")
        if (scope == "Project" and name != "") or (scope != "Project" and not name.strip()):
            raise ValueError(f"{KEY} has an invalid case name for its scope")
        identity = scope, name
        if identity in identities:
            raise ValueError(f"{KEY} has a duplicate scope and case name")
        identities.add(identity)
        result.append(dict(entry))
    return result


def reference_status(entry: dict[str, str]) -> str:
    """State completeness only; the application does not verify a user source."""
    missing = []
    if not entry["document"].strip():
        missing.append("document or record")
    if not entry["locator"].strip():
        missing.append("section/page locator")
    return "Incomplete: " + " and ".join(missing) + " not supplied" if missing else "User-supplied reference"


def replace_entry(register, scope, case_name, document, locator):
    """Edit one exact assignment; clearing both reference fields removes it."""
    entries = validate(register)
    entry = dict(scope=scope, case_name=case_name, document=document, locator=locator)
    validate([entry])
    previous = next((i for i, item in enumerate(entries)
                     if (item["scope"], item["case_name"]) == (scope, case_name)), None)
    if not document.strip() and not locator.strip():
        if previous is not None:
            entries.pop(previous)
    elif previous is None:
        entries.append(entry)
    else:
        entries[previous] = entry
    return entries


def signature(register) -> tuple:
    return tuple(tuple(entry[key] for key in ("scope", "case_name", "document", "locator"))
                 for entry in validate(register))


def available_assignments(inp) -> list[tuple[str, str]]:
    """Read declared identities, without using results or choosing a governor."""
    from app import fatigue_inputs

    def names(value, key):
        # Metadata remains editable while an action operand is incomplete.
        # Read text identities only; the action parser owns numeric validation.
        rows = value.to_dict("records") if hasattr(value, "to_dict") else value
        if not isinstance(rows, (list, tuple)):
            return []
        return [row[key] for row in rows if isinstance(row, Mapping)
                and type(row.get(key)) is str and row[key].strip()]

    identities = [("Project", "")]
    for family in ("plastic", "elastic"):
        if f"{family}_cases" in inp:
            case_names = names(inp[f"{family}_cases"], "name")
        else:
            name = (inp.get(f"{family}_case") or {}).get("id", "")
            case_names = [name] if type(name) is str and name.strip() else []
        identities.extend((family.title(), name) for name in case_names)
    if inp.get(fatigue_inputs.SPECTRUM_TABLE_KEY) is not None:
        identities.extend(("Fatigue", name) for name in names(
            inp[fatigue_inputs.SPECTRUM_TABLE_KEY], fatigue_inputs.SPECTRUM))
    return list(dict.fromkeys(identities))
