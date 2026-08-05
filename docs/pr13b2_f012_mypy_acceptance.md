# PR-13B2 / F-012 strict-mypy acceptance boundary

## Exact base and fresh lineage

- Exact base: `main@33ce159264fcfaab7032d5ef62ee2f27323749eb`.
- Application version: `0.91`.
- Rejected PRs #347, #348 and #350 are negative evidence only. No rejected head or candidate content is reused.
- This slice owns the type gate only. Coverage and Ruff are accepted; dependency security remains the next independent F-012 slice.

## Frozen policy

1. Strict mypy owns four already-green boundaries in exact order: `sector/bridge.py`, `app/bridge_analysis.py`, `app/manual_equation_contract.py` and `app/manual_equation_publication.py`.
2. Python 3.13, strict mode and non-incremental execution are mandatory. The policy contains no plugins, per-module overrides, exclusions, disabled codes, ignore-missing-imports or other unadvertised mypy setting.
3. `follow_imports = silent` is the sole weakened setting. Its waiver records one owner, reason and exit condition; strengthening to `normal` expires the waiver, while later weakening fails the accepted-base ratchet.
4. Each later candidate compares its ordered file inventory and import strength with the policy stored in the exact accepted Git base. Owned files cannot disappear or reorder.
5. Comment-token inspection rejects `# type: ignore` and file-level `# mypy:` directives in every owned file. AST inspection also rejects `typing.no_type_check` and `typing_extensions.no_type_check` decorators through qualified, imported or aliased names. Unrelated strings and locally defined decorators with the same words remain inert.
6. The runner removes `MYPYPATH` and `MYPY_CONFIG_FILE` from its subprocess environment and passes the exact policy through `--config-file`.
7. Pull-request, every-main-push and manual triggers remain unfiltered. Full-history checkout, exact baseline expression, a single-command validator and a single-command executor remain unconditional and failure-propagating.

## Evidence and exclusions

- Focused tests run strict mypy on all four live files, inject an independently controlled return-type defect, attempt comment, decorator and config suppressions, and exercise setting, file, order, waiver, Git-baseline and workflow mutations.
- Directly affected coverage/Ruff/workflow, reproducibility, package-contract and legal tests plus cheap ASCII/version/static guards run before publication.
- No imported-module typing expansion, dependency-security, solver, formula, standard, result, schema, Streamlit, report/manual, package, signing, release, application-version, v0.93 or rejected-head implementation is included.
