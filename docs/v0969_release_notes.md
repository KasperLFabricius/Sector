# Sector 0.96.9 notes

Sector 0.96.9 improves navigation, input editing and review of calculation results.
Supported project schema: 27.

## Prepare and review a project

The navigation separates Section, Materials, Actions, Analysis settings,
Results, Report, Project and recovery, and Help. Project context shows the
calculation state and recovery time. Page, case and result selections remain
available when you return to a workspace.

Input issues link to the affected field and case. Field help remains available
beside editable inputs. Actions use Plastic, Elastic and Fatigue tabs. Plastic and Elastic retain case
management and paste preview. Fatigue contains grouped spectra with basic actions,
cyclic increments and cycle counts, with a link to fatigue analysis settings.
Explicit axes, signs and input conventions remain available beside the tables.

## Set shear, torsion and M-V-T options

The settings use five pages: Checks and methods, Shared reinforcement, Shear,
Torsion, and Combined M-V-T. Shared controls and links to prerequisite settings
help you find the required inputs. The current section preview remains available
beside the settings. Method choices and engineering declarations remain under
the user's control.

## Read results and prepare reports

The result register provides filters, selected-result detail and a complete
comparison table. Case links retain the identity of the selected result.
Reports provide a coverage outline, profile presets and a preview of the
generated PDF. Contextual help and the manual use the same workspace names.

The original Sweco logo is prominent in the interface, report covers, PDF
manual cover and offline HTML manual. Field help, mathematical notation and
engineering explanations remain aligned across these surfaces.

## Portable build

Extract the complete `Sector-v0.96.9-windows-portable` ZIP and run `Sector.exe`.
Keep its `_internal` folder beside the executable. The package includes the
Python runtime. PDF figure export uses Microsoft Edge or another supported
Chromium browser. A SHA-256 sidecar accompanies the ZIP.

The calculation methods, material laws, numerical results and project schema
retain their existing behavior. PDF and offline HTML manuals are separate
downloads. Existing autosave preferences and guarded recovery remain available
in Project and recovery.
