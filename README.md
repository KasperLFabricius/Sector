# Sector

**Reinforced-concrete cross-section analysis for structural engineering.**

Current release: **Sector 0.92**. This is a source/application release; no
Windows executable is published. See [CHANGELOG.md](CHANGELOG.md).

Active development toward Sector 0.93 is governed by the
[v0.93 decision register](docs/v093_decision_register.md) and the detailed
[v0.93 pull-request programme](docs/v093_pr_programme.md). These records do not
change the current 0.92 release behaviour. The frozen decisions are also
available as a [formatted Excel register](docs/sector_v093_decision_register.xlsx),
with the PR-01 evidence recorded in the
[programme acceptance](docs/pr01_v093_programme_acceptance.md).

Sector is a transparent structural calculation tool, not a compliance,
certification, sign-off or code-completeness system. The engineer controls
methods, action sets and coefficients; selected standards supply equations,
references, defaults and warnings. See the governing
[product identity](docs/product_identity.md).

Sector analyses a polygonal reinforced (and optionally prestressed) concrete
cross-section and reports, for the same section:

* **Elastic analysis** - cracked-section concrete and reinforcement stresses
  from long- and short-term action components, including creep.
* **Plastic analysis** - nonlinear bending capacity at a given axial force,
  traced as a full biaxial M-M envelope with optional applied-action utilisation.
* **Elastic outputs and crack width** - concrete/reinforcement stresses,
  cracking threshold, transformed properties and optional crack width `wk`,
  without specified-limit inputs or output-only verdicts.
* **Section capacity checks** - shear, torsion and combined M-V-T checks where
  supported by the selected Eurocode method. Torsional cracking uses the direct
  positive-finite `gamma_ct` input (EN default 1.50; DK/NA default 1.70), and
  reports the actual factor used.
* **Reinforcement detailing checks** - per-case longitudinal minimum
  reinforcement and shear/torsion link ratio and spacing checks, plus a
  section-wide clear-spacing review with stable element IDs.
* **Fatigue analysis** - grouped sustained/basic and cyclic action bins, using
  the cracked elastic section for reinforcing steel, tendons and concrete.
* **Capability-scoped standards provenance** - fatigue routes use stable design-
  basis keys with explicit source and adoption disclosures. The retained
  bridge-source concrete damage-sum method uses user-supplied section actions;
  Sector does not infer semantic bridge components or complete bridge coverage.

Plastic and Elastic identify the calculation method, not the limit state. Each
named row carries the user's project-defined description or classification (for
example ULS, ALS, SLS or FLS). Plastic/capacity rows contain NEd, MxEd, MyEd,
Vx,Ed, Vy,Ed and TEd. Elastic rows contain long- and short-term NEd/MxEd/MyEd components
and optionally request crack width per row. Any user-defined action set is
permitted; Sector does not infer required combinations or code completeness. Fatigue spectra
group named bins with cycle counts and sustained/basic plus cyclic NEd/MxEd/MyEd.

Mild-steel and prestress catalogues provide stable material IDs. Each bar or
tendon is assigned an ID, so mixed strengths, moduli, partial factors, worklines
and tendon prestrains remain traceable in the UI, project file and PDF report.
Fatigue S-N details use separate stable IDs assigned to the same elements.

## Goals

A fast, modern tool with the rigour engineers expect: define a section by its
shape and reinforcement (not by typing coordinates), choose the analysis, press
**Calculate**, and review every named case, the stresses, the capacity envelope,
and the governing results visually. Reports and an in-app manual round it out.

The numerical core is covered by independent hand checks, regression fixtures
and automated tests. Positive finite custom coefficients are used exactly as
entered; deviations from defaults may warn but are not silently clamped or
replaced. The project engineer remains responsible for inputs and method
applicability.

## Running the app

```
pip install --require-hashes -r requirements.txt
python run_app.py          # or: streamlit run app/sector_app.py
```

Sector uses port 8502 so it can run alongside BriCoS on Streamlit's default
port 8501. Both launch methods bind to `127.0.0.1`, so the application is
accessible only from the computer running Sector.

Define the section (shape, dimensions, reinforcement), set the materials, add
named rows to the Plastic/capacity and Elastic load tables, pick the analysis
mode, and press **Calculate**. The section drawing updates live as you type;
results update when you calculate.

## Portable Windows build

The v0.93 programme adds a separate, unsigned portable Windows distribution.
When a provenance-bearing official Sector source ZIP contains the root
`BUILD_SECTOR_PORTABLE.bat`, keep the complete extracted source folder and
double-click that file. The one-time build requires exact 64-bit CPython 3.13.0
and enough disk space; it invokes its internal PowerShell orchestration itself,
does not require administrator elevation, and prints the resulting portable
folder and ZIP paths. No separately entered PowerShell command is part of the
user procedure.

The generated artifact is a complete ONEDIR folder and matching ZIP. Keep or
share the whole folder/ZIP under the Sector licence; `Sector.exe` does not work
as a standalone copied file. The portable application needs neither Python nor
installation at runtime. It is deliberately unsigned, so Windows SmartScreen
or organisational policy may warn or block it; Sector claims no digital
signature, trusted-publisher reputation, installer registration or managed
approval. Do not bypass organisational security policy. Report figures require
a supported Chromium-family browser; Microsoft Edge is the supported Windows
prerequisite and is not bundled.

The portable artifact name is derived from the authenticated source version.
Until PR-09 performs the coordinated 0.93 identity transition and release
qualification, this repository does not claim that a v0.93 portable release
asset has been published.

The solver's inner loops are compiled with Numba, which the app warms up once at
startup (a few seconds, cached on disk thereafter) so every calculation after
that is near-instant. If Numba is not installed the solver still runs, just more
slowly.

## Project layout

```
sector/        computation core (headless, regression-tested)
  geometry     exact polygon area-moment integrals and clipping
  materials    concrete / mild-steel / prestress stress-strain laws
  section      the cross-section model
  elastic      cracked-section elastic stresses
  fatigue      grouped S-N/Miner damage using Elastic long/short states
  plastic      nonlinear capacity (neutral-axis sweep, governing failure)
  capacity     headless shear, torsion, and M-V-T result orchestration
  detailing    modelled-direction reinforcement, link detailing and clear spacing
  serviceability  cracking threshold, tension stiffening, crack width
  bridge       typed decommission marker for retired component-mapped kernels
  design_standards  capability-scoped basis and source registry
  templates    parametric section + reinforcement builders
app/           Streamlit interface and canonical input models
  fatigue_inputs  stable S-N detail catalogue and grouped spectrum schema
  fatigue_analysis  validated application-to-fatigue-engine boundary
  session_state_migrations  bounded current-schema state transitions
tools/         developer tooling (e.g. regression-fixture generation)
tests/         unit tests + the verification regression
```

## Development

```
pip install --require-hashes -r requirements-dev.txt
python -m pytest tests -n 4
```

The four-worker command matches the GitHub QA gate and keeps the solver-heavy
verification cases distributed. Run without ``-n 4`` only when a serial diagnostic
trace is useful. The test suite includes a permanent verification regression; the
whole tree is kept strictly ASCII (enforced by a test).

The live Streamlit UI stages the engineering inputs in a full-width workflow
selector and mounts one active pane in a sequential fragment. A completed pane
render commits the complete canonical input draft; interrupted rapid changes are
recovered from the last complete draft plus the genuine-event journal. View
navigation, result-detail controls, Quick Section, report metadata and save/load
controls use their own safe fragments. Those interactions therefore avoid
rebuilding the complete application workspace in a browser. Streamlit's
``AppTest`` runner always executes a full script rerun and does not emulate browser
fragment reruns; UI tests consequently stage already-rendered widget changes and
submit them together. The Quick Section Apply and Back buttons are the exception:
they deliberately escalate from a fragment to a full-app rerun, so AppTest stages
their input edits once before clicking the exit button. Preserve those patterns
when adding UI coverage so test time tracks engineering work rather than redundant
page construction without retaining a stale fragment tree.

The supported runtime is pinned in `.python-version`. Runtime, development and
Windows-build environments are locked in `requirements*.txt`; edit the matching
`requirements*.in` file and regenerate the lock instead of editing a lock by
hand.

## Distribution

Sector is proprietary software authored by Kasper Lindskov Fabricius and licensed
to Sweco Danmark A/S for internal use. Access to the repository or application
does not grant a personal or public licence. See [LICENSE](LICENSE). Windows builds
include a generated third-party notice bundle beside `Sector.exe`; the source
process is documented in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

The corrective Sector 0.92 source release, tagged `v0.92-source.1`, provides
`Sector-v0.92-source.zip` as the official runnable source/application asset. It
is exported from the exact accepted commit and embeds a self-verifying commit
and file inventory for saved-project, report and optional unsigned-build
provenance without `.git`. Use that asset rather than GitHub's automatic source
snapshots when revision traceability is required. The release contains no
Windows executable or installer. Unsigned Windows QA packages are test evidence
only and must not be launched or distributed.

That internal QA artifact is distinct from the separately named portable
folder/ZIP described above. The protected signing workflow remains a separate,
explicitly authorised path and has no unsigned fallback.
