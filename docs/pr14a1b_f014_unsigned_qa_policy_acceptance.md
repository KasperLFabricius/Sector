# PR-14A1B F-014 unsigned-QA package policy acceptance

## Frozen boundary

This candidate starts from accepted main
`ab4ef9eb77d246a8a32d196ae2e01e7168555a2c`. It owns only the ordinary Windows
build surfaces: the QA workflow, local convenience scripts and packaging guide.
Every ordinary build is explicitly an unsigned, non-distributable QA artifact
for static inspection. No ordinary surface invites a user to launch, zip or
distribute `Sector.exe`, and there is no unsigned release fallback.

## QA identity gate

The QA workflow pins `SECTOR_SOURCE_REVISION` to its exact GitHub commit before
building. Its verification step checks the package structure, the complete
Windows product/version/legal identity, the absence of a company/publisher
identity, and the complete retained provenance manifest. Only after those
checks does it upload the short-lived artifact named
`Sector-Windows-unsigned-QA`.

The warning that the artifact is unsigned and must not be launched or
distributed precedes package creation. The workflow contains no certificate,
secret, protected environment, signing, timestamp or executable-launch path.

## Exclusions

No executable is built or launched locally by this candidate. No signing
authority, release workflow, dependency, product identity, solver/formula,
standard, result/verdict, schema/persistence, Streamlit/UI, report/manual,
cold-start, reproducibility model, application-version or v0.93 change is
included. PR-14A2 owns protected genuine signing. PR-14C owns the controlled
publication build and consolidated full gate.
