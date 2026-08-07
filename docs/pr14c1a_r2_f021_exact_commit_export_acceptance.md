# PR-14C1A-R2 F-021 exact raw-commit export acceptance

## Exact base and boundary

This clean-room replacement starts from accepted main
`80469ec1af101d67884f32d38b69a2071bfa22c1`. It owns one standard-library
primitive that materializes a new isolated source directory from the raw regular
file blobs of one exact lowercase 40-hex commit. Sector remains version `0.91`.

The exact commit object and its raw tree/blob objects are the only source
authority. Mutable worktree bytes, index hints, local attributes and filters,
line-ending conversion, ignored and untracked files, replacement refs, and
inherited Git repository-selection variables cannot influence exported bytes.

## Frozen acceptance matrix

- The repository argument is the exact worktree root and the source identity is
  an exact commit object, never a ref, tag, tree, blob, abbreviation, replacement
  target, or environment-selected repository.
- Every Git subprocess disables replacement objects and receives an environment
  with inherited `GIT_*` variables removed before repository discovery.
- Strict object verification precedes recursive raw-tree inventory. Only regular
  `100644` and `100755` blobs are accepted.
- Symlinks, submodules, traversal, Git-control names, Windows-forbidden names,
  ASCII and superscript-digit device aliases, trailing dot/space names,
  case-folding collisions, canonical Unicode-normalization collisions, and
  file/directory collisions fail before output creation.
- Both the worktree-specific Git directory and linked-worktree common Git
  directory are resolved and excluded from the output boundary.
- Raw blob batch payloads are independently rehashed and matched to their tree
  identities before any output directory is created.
- Output must not exist and cannot contain the repository. A run never deletes
  or overwrites previous evidence; a materialization error preserves its unique
  partial directory for inspection.
- File bytes and executable modes come only from the commit. Deterministic
  file-count, byte-count, and canonical inventory-SHA256 evidence is returned.
- The CLI runs under `python -I -S` with no third-party dependency.

Independent repositories and synthetic tree/batch records cover the complete
boundary, including the three independent defect classes that rejected PR #366.

## Explicit exclusions

This slice does not wire packaging or a build engine. Source epoch, package
identity, two-build comparison, dependency/coverage publication gates, signing,
application behavior, solver mechanics, Streamlit/UI, report/manual content,
schema, version, and v0.93 behavior remain unchanged. PR-14C1B owns isolated
build integration after this primitive is accepted.
