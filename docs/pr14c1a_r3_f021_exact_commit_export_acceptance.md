# PR-14C1A-R3 F-021 exact raw-commit export acceptance

## Exact boundary

This clean-room replacement starts from accepted main
`80469ec1af101d67884f32d38b69a2071bfa22c1`. It owns one standard-library
primitive that materializes a new directory from the authenticated regular-file
tree of one exact lowercase 40-hex commit. Sector remains version `0.91`.

The requested commit and its recursively referenced tree/blob objects are the
only source authority. Mutable worktree bytes, index hints, attributes, filters,
line-ending conversion, ignored and untracked files, replacement refs, inherited
Git controls, unrelated object-database contents, and configurable fsck policy
cannot influence the exported source.

## Frozen acceptance matrix

- The repository argument is the exact worktree root and the source identity is
  an exact commit object, never a ref, abbreviation, tag, tree, or blob.
- Every Git subprocess disables replacement objects and receives an environment
  with all inherited `GIT_*` variables removed before repository discovery.
- Verification is limited to the selected commit's source closure. The exporter
  independently authenticates each raw commit, tree, and blob payload against
  its requested SHA-1 identity instead of trusting repository-wide fsck policy.
- The raw commit has one leading tree, well-formed parent identities, and exactly
  one strict author and committer identity. Duplicate parents fail closed.
- Raw tree objects are recursively parsed in canonical Git order. Only tree mode
  `40000` and regular-file modes `100644`/`100755` are accepted.
- Symlinks, submodules, traversal, Git-control names, non-UTF-8 names,
  Windows-forbidden names and device aliases (including superscript digits),
  trailing dot/space names, case and Unicode collisions, and file/directory
  collisions fail before output creation.
- Both the worktree-specific and linked-worktree common Git metadata directories
  are excluded from the output boundary.
- Blob payloads are batch-read and independently rehashed before any output is
  created. File bytes and executable modes come only from the commit.
- The output must not exist as any filesystem entry. A symlink-aware check runs
  before path resolution, so a dangling destination symlink cannot redirect the
  export. A run never deletes or overwrites prior evidence; any materialization
  failure leaves its unique partial directory available for inspection.
- Deterministic file-count, byte-count, and canonical inventory-SHA256 evidence
  is returned. The CLI runs under `python -I -S` without third-party packages.

The focused oracle includes the five independent defect classes preserved on
closed PRs #366 and #367: inherited repository selection, linked-worktree common
metadata, superscript Windows device aliases, unrelated malformed objects, and
mutable fsck severity/skip-list policy.

## Recorded evidence

- Focused exact-export oracle: 51 passed; one real-symlink integration probe was
  skipped because this Windows account cannot create directory symlinks. The
  deterministic symlink-aware pre-resolution oracle passed.
- Accepted-main export: 228 files / 5,943,989 bytes / inventory SHA-256
  `88dce61f9f634acba8494b02128f84e8cb7295e9001367f6ac1e871a3f3b33c9`.
- Exported `app/sector_app.py` independently matched raw blob
  `dc667366f79a1613652dc75594b90372e5f8ab5c`; no Git metadata was exported.

## Explicit exclusions

This slice does not invoke packaging or a build engine. Source epoch, package
identity, two-build comparison, dependency/coverage publication gates, signing,
application behavior, solver mechanics, UI, report, manual, schema, version, and
v0.93 behavior remain unchanged. PR-14C1B owns isolated build integration after
this primitive is accepted.
