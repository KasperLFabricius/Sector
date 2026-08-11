# PR-08 Sector v0.93 portable Windows packaging acceptance

Status: accepted and merged as PR #390. Reviewed head
`6847246b26fb7d598f909fac6a93628e8e914597` and accepted tree
`b47d4acfe1112a512d31ece0e300e7837bb304e6` passed Sector QA run
`31491022341`; squash `470bbfbc4a80be524d32d1fd6f9509a1c60deede`
has the same tree. Final portable artifact ID `9103299450` has artifact digest
`b581f70c7c29f28bf3cec2437563a4d3e49740aa2abd3c1d05b1403e22fc19dc`.

## Accepted upstream base

- Programme branch: `codex/pr08-v093-portable-build`
- Upstream PR-07B squash revision: `47be3326fa4abad5acdc356435dbeeed28d31d95`
- Accepted upstream tree: `56266e0868093bc26e7bedcd1472721f3b60fb6d`
- Governing identity: [Sector product identity](product_identity.md)
- Living programme: [Sector v0.93 PR programme](v093_pr_programme.md)
- Decision register: [Sector v0.93 decision register](v093_decision_register.md)
- Upstream acceptance: [PR-07B report/manual profiles acceptance](pr07b_v093_report_manual_profiles_acceptance.md)

PR-07B passed its exact-head complete test, real report/manual render and
two-build unsigned-package workflows before squash merge. PR-08 starts from
that accepted squash without changing an engineering calculation, project
schema or current product version.

## Owner-confirmed objective

PR-08 adds a separate user-facing portable Windows build. From an extracted
official Sector source ZIP, the user double-clicks
`BUILD_SECTOR_PORTABLE.bat`; the wrapper locates its own source root, invokes
the internal PowerShell orchestration, authenticates the embedded exact-source
closure, builds in an isolated new directory and publishes one complete
unsigned ONEDIR folder plus a deterministic ZIP and verification receipts.

The existing unsigned-QA two-build path remains internal and non-distributable.
The protected signing workflow remains separate, dormant and without an
unsigned fallback. No signing key, certificate, secret or protected environment
is used by the portable path.

## Portable distribution contract

The final create-only output directory contains one version-derived folder named
`Sector-v<version>-windows-portable-unsigned`, its same-named ZIP, an archive
SHA-256 sidecar and a canonical distribution receipt. The folder contains at
least:

```text
Sector.exe
_internal/
README-PORTABLE.txt
LICENSE
THIRD_PARTY_NOTICES.txt
sector_build_info.json
package_manifest.json
SHA256SUMS.txt
```

The directory name and README say `unsigned`. The README states that the whole
folder or ZIP is the distributable unit, no installation or administrator
rights are required, Windows SmartScreen or corporate policy may warn or block
execution, the package claims no trusted publisher or reputation, and use or
sharing remains subject to the proprietary Sector licence. Report figures
continue to require Microsoft Edge on Windows; Edge supplies the supported
Chromium-family browser implementation and is not bundled.

PR-08 deliberately derives the artifact label from the authenticated runtime
identity. It therefore remains `v0.92` on this branch. PR-09 owns the single
coordinated transition to `v0.93` and must regenerate and reverify the final
release assets after that identity change.

## Trust and source boundary

An extracted source release is accepted only when its embedded commit object,
tree identity, per-file object IDs, byte counts and canonical inventory digest
agree and the requested revision matches. The source root and every inventoried
entry must be ordinary, no-follow files or directories; links, junctions,
reparse points, special files, missing files and extra files fail closed.

That embedded closure proves consistency with the selected source revision. It
does not by itself prove publisher origin. Official-release status therefore
also depends on the trusted release channel and externally published source ZIP
SHA-256. Neither the builder nor its README overclaims signature, publisher or
origin authentication.

Build work and final outputs are outside the authenticated source directory.
Every destination is create-only. Assembly occurs in a private staging
directory and the final portable output surface becomes visible only after package,
manifest, archive and sidecar verification. An existing output is preserved;
a failed build publishes no final portable ZIP.

## Determinism and archive safety

The portable manifest inventories every application and user-document file by
canonical relative path, byte count and SHA-256 and binds the exact source
revision, tree, version and unsigned status. `SHA256SUMS.txt` authenticates all
folder files except itself. The sibling receipt binds the folder inventory and
final ZIP digest without absolute paths or wall-clock values.

ZIP names use one canonical POSIX root. Verification rejects absolute and drive
paths, `..`, empty or dot components, backslashes, Unicode/case-fold collisions,
duplicate entries, link or special-file metadata, noncanonical timestamps or
modes, comments, prefix/trailing data, and any missing, extra or changed file.
Two independent producer jobs under the accepted Windows environment must
publish immutable remote artifacts. A separate consumer downloads, verifies
and compares both complete folders, manifests, ZIPs, sidecars and receipts for
byte identity. The final gather uses those two distributions only as immutable
verification inputs, then publishes one verified producer-A distribution plus
the comparison and smoke evidence; it does not duplicate producer B in the
canonical portable artifact.

## Controlled startup smoke

The ordinary user launcher still opens the local browser at
`127.0.0.1:8502`. The acceptance tool alone selects an unused loopback port and
sets the explicit packaged-launcher headless control so no browser opens. It
extracts the already verified ZIP through the safe archive boundary, starts the
packaged executable suspended, assigns it to a kill-on-close Windows Job Object
before resuming it, and gives it only an allowlisted environment with isolated
writable directories. It accepts Streamlit's exact local health response only
when the Windows TCP owner table proves the listener belongs to that job both
before and after the response. Cleanup terminates, waits and closes the whole
job even if its root process already exited, then proves the port is closed.
Timeout, early exit, unowned listener, non-loopback binding or cleanup failure
is a test failure.

## Affected-surface matrix

| Surface | PR-08 change | Frozen boundary |
| --- | --- | --- |
| Root entry point | Add `BUILD_SECTOR_PORTABLE.bat` and internal portable PowerShell orchestration. | Double-click is the only user action; no administrator elevation or separately entered PowerShell command. Existing QA wrappers retain their non-distributable policy. |
| Exact source | Extend no-Git verification to reject root/entry links and Windows reparse points before following them. | Embedded closure is not described as a publisher signature; official-channel hash remains external. |
| Exact package verification | Reuse the existing raw-snapshot product/source verifier for Git and verified extracted-source inputs. | No verification against mutable exported build files; existing signed-release and QA checks retain their semantics. |
| Portable assembly | Add canonical folder metadata, complete inventory, deterministic ZIP, SHA-256 sidecar and distribution receipt. | Complete ONEDIR only; no one-file executable, installer, registry mutation or overwrite. |
| Packaged launcher | Add one explicit acceptance-only headless control. | Default launch remains local-only and browser-opening; calculation/app behaviour is unchanged. |
| Startup acceptance | Add a standard-library Job Object and TCP-owner-bound loopback health tool. | CI-controlled only; no inherited workflow/secret environment, local browser, numeric-PID fallback or broad process termination. |
| CI topology | Add independent producer A/B jobs with immutable uploads, a comparison consumer, a disposable smoke consumer of verified A only, and a final re-verifying gather that publishes one distribution plus evidence. | The executable cannot mutate the remotely stored distribution later published; producer B remains verification input rather than a duplicate release payload. Existing unsigned-QA reproducibility job remains separate; protected signing workflow and environment are untouched. |
| Documentation | Separate user portable guidance from internal QA and signed-release guidance. | No signature, trusted publisher, installation, administrator or certification claim. |

## Engineering and release exclusions

PR-08 changes no formula, solver, result, result status, input model, project
schema, report profile or manual equation. Runtime/publication version remains
0.92 and project schema remains 24 until PR-09. It adds no generic calculation
trace/evidence payload, recorder, DAG, persisted result history or replacement
calculation evaluator.

PR-08 does not sign code, create an installer, request elevation, bundle a
browser, publish a production approval, create a GitHub release or update the
runtime identity to 0.93. Those boundaries remain with the protected signing
policy or PR-09 as explicitly assigned by the programme.

## Required acceptance evidence

The final exact candidate must record:

- focused source-release, package-verifier, portable archive, batch/PowerShell,
  launcher and startup-smoke tests;
- traversal, absolute-path, collision, link/reparse, mutation, incomplete
  inventory, existing-output and malformed-receipt adversaries;
- extracted official-source operation from a non-repository path containing
  spaces and a OneDrive-style directory name;
- policy assertions proving no secret, certificate, protected environment,
  signature or installer claim enters the portable path;
- two independently uploaded complete portable builds, followed by remote
  download, verification and byte-identity evidence;
- one disposable clean verified-A extraction that reaches the owned loopback
  health endpoint, terminates its complete Job Object with no browser launch,
  and is never used as the publication copy;
- one final fresh download that re-verifies the immutable distribution before
  the canonical artifact upload without executing `Sector.exe`;
- the consolidated publication/dependency/Ruff/strict-mypy gates and relevant
  full test suite; and
- an independent final Codex P0-P2 review plus the exact GitHub head, tree,
  workflow run, artifact IDs/digests, squash revision and merged-tree parity.

All listed receipts exist on the exact accepted head recorded above. The full
gate, both producers, immutable comparison, controlled startup smoke and final
portable gather passed before squash merge; the programme status is `Merged`.
