"""Searchable authored manual sections without evaluating figure functions."""

from __future__ import annotations

from app import manual_information_architecture as manual_ia


PAGE_HELP = {
    "section": "Define the outline, voids, reinforcing bars and tendons. Use Quick Section or the point tables. Review the drawing and material assignments before calculation.",
    "materials": "Choose the material family and catalogue entry. Each question mark explains the adjacent input. A preset fills the stated material law; review the editable values and diagram.",
    "actions": "Select the Plastic, Elastic or Fatigue tab. Fatigue contains grouped spectra with basic actions, cyclic increments and cycle counts. Review names and units. Open Axes, signs and paste rules for the input conventions. Use the field guide for each table column.",
    "settings": "Select a settings group. Shear, torsion and M-V-T has five pages. The shared reinforcement page supplies common member inputs. Select a check explicitly before calculation.",
    "results": "Review the governing rows and their conditions. Select a row to see its numerical result and criterion. Open selected result retains that case. Recalculate when inputs change.",
    "report": "Complete document details and references, then choose Brief, Standard or Audit. Review the coverage and generate the report. The preview and download use the same current PDF.",
    "project": "Save a project file for transfer or deliberate record keeping. Autosave creates a separate recovery file at the selected interval. Review the source and time before restoring a recovery copy.",
}

PAGE_DESTINATIONS = {
    "section": "section", "materials": "material-parameters",
    "actions": "loads", "settings": "analysis-settings",
    "results": "results-overview", "report": "report-workspace",
    "project": "project",
}


def requested_topic(index, topic):
    """Resolve authored page help to its registered manual heading."""
    key = "status-reference" if topic == "result-status" else PAGE_DESTINATIONS.get(topic)
    if key is None:
        return None
    heading = manual_ia.destination(key).heading
    return next((entry for entry in index if entry["title"] == heading), None)


def sections(parts):
    """Index complete heading sections, retaining their original block positions."""
    result = []
    for part, entries in parts.items():
        starts = [i for i, entry in enumerate(entries) if entry.block[0] in {"h1", "h2", "h3"}]
        for index, start in enumerate(starts):
            level = int(entries[start].block[0][1])
            end = next((following for following in starts[index + 1:]
                        if int(entries[following].block[0][1]) <= level), len(entries))
            words = []
            for entry in entries[start:end]:
                block = entry.block
                if block[0] in {"md", "h1", "h2", "h3"}:
                    words.append(str(block[1]))
                elif block[0] in {"table", "callout"}:
                    words.extend(str(value) for value in block[1:])
            result.append({"part": part, "start": start, "end": end,
                           "title": str(entries[start].block[1]), "text": " ".join(words)})
    return result


def search(index, query):
    terms = str(query or "").casefold().split()
    return [entry for entry in index if terms and all(term in entry["text"].casefold() for term in terms)]
