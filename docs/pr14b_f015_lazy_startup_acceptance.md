# PR-14B F-015 lazy startup acceptance

## Candidate boundary

- Exact accepted base: `af23b3c89751d19f7146f588434eb89d69bd06fd`.
- Eight readable files; one `[skip ci]` candidate commit; Sector `0.91`.
- The stable `sector` public API, module access, calculation identities and
  retained monkeypatch seams remain unchanged.
- This slice changes when optional code is imported, never which numerical path
  is selected after the engineer requests a calculation.

## Implemented contract

1. `import sector` loads release metadata and an explicit lazy public registry
   using only the standard library. Every existing public export and historical
   `from sector import <module>` route resolves and is cached on first use.
2. Capacity and detailing retain their authoritative low-level solver calls but
   do not import elastic, plastic or Numba kernels merely to expose method
   choices and application orchestration.
3. The Streamlit entry point defers hidden analysis, persistence, presentation,
   plotting and solver modules. Hidden material previews pass inert builders so
   collapsed stages cannot resolve Plotly accidentally.
4. The default Analysis settings run leaves bridge analysis, result publication,
   visualization, elastic/fatigue, plastic/Numba kernels, serviceability/SLS,
   combined, shear and torsion modules unloaded. Each resolves on its first real
   use and then follows the retained implementation.
5. The packaged launcher immediately prints that Sector is starting and that
   the browser opens when the interface is ready, before importing Streamlit.
   No executable is built or launched by this slice.

The three fatigue concrete method labels needed by the lightweight settings
panel are pinned against the authoritative `sector.fatigue` identities in the
focused test. The active fatigue adapter still validates and executes the
solver-owned method when fatigue is requested.

## Measured cold-start evidence

The pre-slice evidence was captured from the exact base in fresh processes:

- bare `import sector`, seven samples: median `1429.105 ms`;
- default Streamlit `AppTest`, three samples: `5970.1`, `5634.8`, and
  `5694.9 ms` (median `5694.9 ms`).

The candidate evidence uses the same fresh-process boundaries:

- bare `import sector`, seven samples: `4.978`, `4.014`, `4.553`, `4.291`,
  `4.318`, `5.062`, and `4.506 ms`; median `4.506 ms`;
- default Streamlit `AppTest`, three samples: `4256.3`, `4513.2`, and
  `4260.2 ms`; median `4260.2 ms`, with no application exceptions.

The Streamlit median therefore falls by about 25 percent while the bare public
package import falls by more than 99 percent. Timing is descriptive evidence;
the acceptance gate pins the actual unloaded-module boundary rather than a
machine-specific wall-clock threshold.

## Focused and affected evidence

- Lazy registry, isolated import, proxy failure/retry, solver-seam, default-app
  module inventory, method identity and launcher-order matrix: `10 passed`.
- Capacity, detailing, project persistence, packaging, default app, hidden
  preview, plastic calculation and elastic calculation matrix: `314 passed`.
- ASCII/version guards, Ruff, pyflakes, `py_compile`, import smoke, exact base,
  scope, version and rejected-ancestry checks are candidate-freeze gates.

## Explicit exclusions

No solver formula, standard, material law, result, verdict, input value,
persistence schema, report/manual content, calculation-trace restoration,
dependency version, package composition, signing policy, release activation,
application-version or v0.93 roadmap behavior is changed. PR-14C owns the
publication activation and consolidated full regression/report/manual/package/
workflow/UI gate.
