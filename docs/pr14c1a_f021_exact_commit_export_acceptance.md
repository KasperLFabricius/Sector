# PR-14C1A F-021 exact raw-commit export acceptance

## Exact base and boundary

This clean-room slice starts from accepted main
`80469ec1af101d67884f32d38b69a2071bfa22c1`. It owns only a standard-library
primitive that materializes a new source directory from the raw regular-file
blobs of one exact lowercase 40-hex commit. Sector remains version `0.91`.

The exporter does not validate or copy mutable worktree files. Every Git command
disables replacement objects. The exact commit tree and raw blob objects are the
only source authority; index hints, local attributes, clean filters, ignored and
ordinary untracked files, line-ending checkout rules and worktree modifications
cannot influence the exported bytes.

## Acceptance matrix

- The source identity must name an exact commit object, never a ref, tag, tree or
  blob. Replacement refs cannot redirect commit, tree or blob inspection.
- Only regular `100644` and `100755` blob entries are accepted. Symlinks,
  submodules, unsafe Windows paths, traversal, case collisions, Unicode
  normalization collisions and file/directory collisions fail closed.
- Strict Git object verification precedes export. Every batch payload is then
  independently rehashed as a raw Git blob and matched to its tree identity
  before any output directory is created.
- Output must not exist. A run never overwrites or removes prior evidence; any
  materialization failure leaves its unique partial directory available for
  inspection.
- Exported file paths, bytes and executable modes come only from the exact commit.
  `.git`, ignored files, untracked files and mutable worktree content are absent.
- The isolated CLI runs under `python -I -S` and returns deterministic file-count,
  byte-count and canonical inventory SHA-256 evidence.

Independent repositories cover replacement refs, hostile local attributes,
`assume-unchanged`, `skip-worktree`, ignored payload, untracked payload, malformed
identity, non-commit identity, existing output and hostile synthetic tree entries.

## Explicit exclusions

This primitive is not yet wired into local or hosted packaging. No build script,
package manifest, source epoch, PyInstaller archive, two-build comparison,
workflow, dependency lock, coverage floor, signing, application, solver, report,
manual, UI, schema, version or v0.93 behavior is changed. PR-14C1B owns isolated
build integration after this primitive is independently accepted.
