# PR-15 Sector 0.92 source/application release acceptance

## Frozen boundary

- Exact base: `main@df46a1979ff205da0d0416eddfe45580a47d87c4`.
- Base tree: `d78b4e2529fbab2fa72fc920d5cff97e7b2a5e8e`.
- QA workbook: `Sector_QA_Review_2026-07-31.xlsx` with immutable SHA-256
  `1DE1CA43F0155A282BE7228DFB8480189301071EC21A38DECB34254ABFCC9854`.
- Product release: Sector `0.92`.
- Project schema: version `23`, unchanged.

The accepted PR-01 through PR-14 programme remains historical evidence at
version 0.91. PR-15 changes release identity and publication records only; it
does not change an engineering equation, solver, default, result, project
schema, user workflow or accepted programme lineage.

## Release deliverables

The release consists of the annotated `v0.92` tag, the GitHub Release record
and the attached `Sector-v0.92-source.zip` asset. The archive is produced from
the authenticated raw tree of the exact accepted squash commit by
`tools/build_source_release.py`. It embeds
`sector/sector_build_info.json`, including the exact revision, tree, commit
time and source inventory, so saved projects and reports retain accepted-commit
provenance after extraction without `.git` metadata. The sources run the local
Streamlit application through the locked requirements and commands documented
in `README.md`.

GitHub's automatic source-code ZIP and TAR links do not embed that manifest and
are not the provenance-bearing runnable release asset.

No EXE, MSI or unsigned QA package is a release asset. No signed executable,
publisher identity, certificate, timestamp, reputation or administrator
approval is claimed. Ordinary Windows builds remain explicitly unsigned QA
evidence that must not be launched or distributed. The protected Windows
signing workflow remains manual-only and is not dispatched by the `v0.92` tag
or source release.

Static Windows version metadata and its fail-closed verification contracts move
to `0.92.0.0` so a future authorized build cannot disagree with the source
identity. This consistency update is not a Windows production release.

## Acceptance conditions

1. The source, app, report/manual provenance, README and changelog resolve the
   current release from the single `sector.__version__ == "0.92"` identity.
2. Windows resource, unsigned-QA and protected-signing verification surfaces
   agree on `0.92.0.0` without adding signing or launch authority.
3. Historical 0.91 acceptance documents and compatibility fixtures remain
   unchanged, except for the transparent release-transition link in the final
   programme closure map.
4. Focused local release, identity, policy, closure and lazy-startup tests pass,
   followed by the complete exact-head Sector QA workflow.
5. Exact-head Codex Review has no unresolved P1 or P2 thread, and the accepted
   candidate tree is verified after squash merge.
6. The `v0.92` tag, source ZIP manifest and source-only GitHub Release resolve
   to that exact squash commit. The source ZIP is independently reverified
   before upload, its SHA-256 is recorded in the release, and the release has no
   Windows binary asset.

This acceptance is implementation QA, not engineering certification. A
qualified engineer remains responsible for inputs, standards applicability,
independent verification, design judgement and acceptance of every result.
