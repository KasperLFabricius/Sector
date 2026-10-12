# Sector 0.96.7 notes

Sector 0.96.7 improves the structure, explanations and presentation of reports.
Supported project schema: 27.

## Read the report

The results overview links each governing result to its source and scope notes.
The effective inputs follow the overview. Separate material-property schedules
make each assigned law and value easier to locate. A method register identifies
the selected design basis for each calculation family.

Standard groups related final results and gives the source for each result.
Audit also gives the detailed calculation sequences, numerical substitutions
and retained intermediate evidence. Brief gives the governing outcomes.
Every profile includes the geometry, materials, loads and relevant options,
including inputs for requested checks that have no assessed result.
The profiles preserve the same engineering values,
criteria, statuses and rounding rules.

Larger text, shorter paragraphs and separate equations improve reading at the
printed page size. Table continuations retain their identities and headings.

## Read the figures

With figures enabled, Standard and Audit show section coordinates and element
IDs. An inset gives one identified case's concurrent actions and sign convention.
Crack-control diagrams show the effective concrete area and the included
reinforcement when the accepted calculation supplies the required evidence.
Circles identify bars, and diamonds identify tendons. Filled markers identify
included reinforcement; open markers identify other reinforcement.
The diagrams also show the accepted reference-stress neutral axis and governing
clear cover. Standard gives the effective reinforcement areas and ratio beside
the diagram. Audit gives the detailed numerical calculation.

Longitudinal-chord diagrams compare simultaneous demand and conditional
resistance for each assessed physical face. These diagrams require complete,
current chord evidence. Stress and strain maps retain their state, signs,
scales, captions and extrema tables.

## Portable build

Extract the complete `Sector-v0.96.7-windows-portable` ZIP and run `Sector.exe`.
Keep its `_internal` folder beside the executable. The package includes the
Python runtime. PDF figure export uses Microsoft Edge or another supported
Chromium browser. A SHA-256 sidecar accompanies the ZIP.

The calculation methods and project schema retain their existing behavior.
