# PR-16 Sector 0.92 extracted-source build correction

## Defect boundary

The original `v0.92` source/application archive correctly retained runtime
revision provenance without `.git`, but `packaging/build.ps1` still required Git
to resolve that revision and `tools/build_exact_commit.py` could only export Git
objects. Double-clicking `packaging/build.bat` from the official extracted
archive therefore stopped before PyInstaller with `Cannot resolve the exact
source revision`.

This correction changes source-release packaging and unsigned QA build
provenance only. It does not change an engineering equation, solver, default,
result, project schema, user workflow, signing policy or administrator
requirement. Sector remains version `0.92`.

## Corrected contract

1. Git checkouts continue to export and authenticate the requested raw commit
   object and tree without reading mutable worktree files.
2. A generated source release carries manifest schema 2: the raw commit payload
   plus the canonical path, mode, Git blob identity and byte count for every
   tracked file.
3. A no-`.git` build validates the commit SHA-1, commit tree and time, rebuilds
   the complete Git tree identity, verifies the SHA-256 source inventory, checks
   every blob and rejects changed, missing, additional, linked or special paths
   before creating isolated build source.
4. The release manifest is not copied into the isolated commit tree. Generated
   notices and build metadata therefore retain their existing create-only paths.
5. Default QA evidence is written to a unique sibling directory, keeping an
   extracted release immutable and allowing repeat builds from the same clean
   input.
6. The resulting Windows package is still unsigned static QA evidence only. It
   must not be launched, zipped or distributed and is not a release asset.

## Publication

The immutable `v0.92` tag and its original asset remain historical evidence.
The corrected exact source snapshot is published under the corrective tag
`v0.92-source.1` with the same application identity and source-only asset name,
`Sector-v0.92-source.zip`. No EXE, MSI or installer is attached.
