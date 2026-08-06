# PR-14C1 F-021 packaged-source purity acceptance

## Exact base and boundary

This slice starts from accepted main
`80469ec1af101d67884f32d38b69a2071bfa22c1`. It owns only the local controlled
package preflight that proves recursively packaged source trees contain no bytes
outside one exact commit. Sector remains version `0.91`.

The immutable identities are the exact lowercase 40-hex current `HEAD`, a clean
tracked tree, and the complete untracked inventory beneath `app`, `sector` and
`assets`. Because the retained PyInstaller specification recursively adds those
trees, ignored files are package inputs and cannot be excluded from inspection.

## Acceptance matrix

- The requested revision must be exact and equal current `HEAD`.
- Staged changes and actual filtered worktree bytes are compared independently
  with `HEAD`; `assume-unchanged` and `skip-worktree` hints cannot mask changes.
- Every untracked entry beneath a packaged source root fails, whether ignored or
  ordinary, including bytecode, native libraries, caches and private assets.
- Untracked and ignored artifacts outside packaged source roots remain present,
  inert and permitted.
- Git execution failure, malformed identity or an unavailable repository fails
  closed with no package build.
- The preflight uses only the Python standard library and Git, runs under
  `python -I -S`, and never deletes, moves, stages or rewrites an artifact.

Independent temporary-repository tests cover clean, staged, dirty tracked,
`assume-unchanged`, `skip-worktree`, mismatched revision, ignored payload,
ordinary untracked payload, outside-root artifact and isolated-CLI branches.
The build contract pins the preflight before dependency installation and
PyInstaller execution.

## Explicit exclusions

No package timestamp, deterministic two-build comparison, archive
canonicalization, workflow, dependency lock, coverage floor, signing,
application, solver, report, manual, UI, schema, version or v0.93 behavior is
changed. Later PR-14C slices own exact source-epoch identity, reproducibility and
publication activation.
