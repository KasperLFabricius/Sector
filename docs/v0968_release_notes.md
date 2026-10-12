# Sector 0.96.8 notes

Sector 0.96.8 improves result figures, notation and recovery of saved inputs.
Supported project schema: 27.

## Read section results

Plastic and Elastic results show one section contour at a time. Select Stress
or Strain. For Elastic results, select combined or sustained actions. The
selected case, duration, units and exact extrema remain beside the figure.

Bar and tendon markers identify tension, compression and zero values in
addition to the numerical color scale. Hover text identifies each element,
material and strain definition. Compatible section strain, material strain and
initial tendon strain retain their distinct meanings. Concrete tensile stress
remains zero under the existing material laws.

The supporting tables retain the full element and concrete-corner values.
Reports can show separate stress and strain figures for the required states.

## Read values and explanations

Result labels, engineering notation and method explanations use consistent
quantities and units. Known calculation limitations retain their engineering
explanations and assessment status.

## Recover completed inputs

Autosave starts enabled with a two-minute interval. Existing explicit autosave
preferences remain in effect. An open session can save completed inputs while
idle. Atomic writes protect the recovery file, and a concurrent session change
prevents an automatic overwrite. Use the Project controls to save a separate
project file and manage autosave preferences.

## Portable build

Extract the complete `Sector-v0.96.8-windows-portable` ZIP and run `Sector.exe`.
Keep its `_internal` folder beside the executable. The package includes the
Python runtime. PDF figure export uses Microsoft Edge or another supported
Chromium browser. A SHA-256 sidecar accompanies the ZIP.

The calculation methods, numerical criteria and project schema retain their
existing behavior. PDF and offline HTML manuals are separate downloads.
