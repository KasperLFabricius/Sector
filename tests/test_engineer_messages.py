"""Independent positive-provenance checks for engineer-facing diagnostics."""

from __future__ import annotations

import ast
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app import engineer_messages
from sector.capacity import (
    CapacityInputError,
    CapacityResultError,
)
from sector.engineer_message import EngineerMessage


# This corpus is deliberately test-owned. It imports no production vocabulary
# constants, so weakening the application policy cannot weaken the oracle.
HOSTILE_COMPOSITE = (
    "RAW-LEAK-7Q GitHub PR #812 git_commit SHA-256 payload-schema contract "
    "internal_private_ID EQ-RAW-77 source-control development-history "
    "solver traceback filesystem C:/private/work/item.json"
)
HOSTILE_CORPUS = (
    HOSTILE_COMPOSITE,
    "pull_request 19 contains a git commit hash",
    "development/process metadata migration",
    "private-key and internal_identifier in a JSON payload",
    "EQ-CAPACITY-401 failed in the solver state",
    "source revision abc123 from GitHub",
    "Traceback: File C:/private/model.py, line 81",
    "safe-looking plain text must still be untrusted",
    "",
)
ENGINEERING_NOTATION = (
    "gamma_Ff, gamma_s, gamma_V, gamma_c,fat, beta_cc(t0), alpha_cc, "
    "f_ck, f_yk, f_pk, f_p01k, N_Ed, M_Ed, V_Ed, T_Ed and V_Rd,c "
    "must remain visible exactly"
)
FALLBACK = EngineerMessage(
    "TEST-FALLBACK",
    "Review the current engineering inputs and try again",
)


class _UnknownObject:
    def __str__(self) -> str:
        return HOSTILE_COMPOSITE


class _MessageError(ValueError):
    def __init__(self, message: EngineerMessage) -> None:
        super().__init__("private diagnostic")
        self.engineer_message = message


def _visible(value: object) -> str:
    return engineer_messages.error_detail(
        value,
        fallback=FALLBACK,
        context="independent hostile-corpus test",
    )


@pytest.mark.parametrize("diagnostic", HOSTILE_CORPUS)
def test_full_raw_hostile_corpus_falls_back_and_logs(diagnostic, caplog):
    assert _visible(diagnostic) == FALLBACK.text
    assert HOSTILE_COMPOSITE not in _visible(diagnostic)
    assert "Suppressed untrusted diagnostic" in caplog.text


@pytest.mark.parametrize(
    "diagnostic",
    (
        ValueError(HOSTILE_COMPOSITE),
        OSError(HOSTILE_COMPOSITE),
        CapacityResultError(HOSTILE_COMPOSITE),
        _UnknownObject(),
        {"message": HOSTILE_COMPOSITE},
    ),
)
def test_unknown_objects_exceptions_and_result_errors_fail_closed(
    diagnostic,
    caplog,
):
    assert _visible(diagnostic) == FALLBACK.text
    assert "Suppressed untrusted diagnostic" in caplog.text


def test_engineer_message_is_immutable_neutral_and_not_a_string():
    message = EngineerMessage("TORSION-INPUT", "Review the torsion wall thickness")

    assert not isinstance(message, str)
    with pytest.raises(FrozenInstanceError):
        message.text = "changed"


def test_trusted_message_and_recognised_notation_survive_exactly():
    message = EngineerMessage("EC-NOTATION", ENGINEERING_NOTATION)

    assert _visible(message) == ENGINEERING_NOTATION
    assert _visible(_MessageError(message)) == ENGINEERING_NOTATION


def test_ordinary_engineering_words_are_not_false_suppressions():
    text = (
        "The stable section response is retained as the authoritative result; "
        "the material identity is stated in the input table"
    )

    assert _visible(EngineerMessage("ENGINEERING-WORDS", text)) == text


def test_mixed_notation_and_development_text_falls_back(caplog):
    message = EngineerMessage(
        "MIXED-COPY",
        "gamma_V is 1.40 in GitHub PR #812 and SHA-256 payload data",
    )

    assert _visible(message) == FALLBACK.text
    assert "Suppressed untrusted diagnostic" in caplog.text


def test_json_round_trip_loses_message_trust(caplog):
    encoded = json.dumps({"code": "EC-NOTATION", "text": ENGINEERING_NOTATION})
    decoded = json.loads(encoded)

    assert _visible(decoded) == FALLBACK.text
    assert _visible(decoded["text"]) == FALLBACK.text
    assert "Suppressed untrusted diagnostic" in caplog.text


def test_capacity_input_error_requires_explicit_attached_message():
    raw = CapacityInputError(ENGINEERING_NOTATION)
    trusted = CapacityInputError(
        "private diagnostic",
        engineer_message=EngineerMessage("CAPACITY-INPUT", ENGINEERING_NOTATION),
    )

    assert _visible(raw) == FALLBACK.text
    assert _visible(trusted) == ENGINEERING_NOTATION


def test_runtime_and_static_copy_checks_share_separator_normalisation():
    variants = (
        "GiThUb",
        "pull_request 44",
        "git-commit",
        "SOURCE_control",
        "development/history",
        "SHA256",
        "internal.private.identifier",
        "EQ_PRIVATE_99",
    )

    for value in variants:
        assert engineer_messages.development_process_terms(value)


def test_fallback_must_be_an_authored_engineer_message():
    with pytest.raises(TypeError, match="EngineerMessage"):
        engineer_messages.error_detail(
            "detail",
            fallback="Review the inputs",
            context="test",
        )


def _engineer_message_constructor_violations(tree: ast.AST) -> list[int]:
    aliases = {"EngineerMessage"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {
            "sector.engineer_message",
            "app.engineer_messages",
        }:
            for name in node.names:
                if name.name == "EngineerMessage":
                    aliases.add(name.asname or name.name)

    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = node.func.id if isinstance(node.func, ast.Name) else None
        if called not in aliases:
            continue
        literal_args = (
            len(node.args) == 2
            and not node.keywords
            and all(
                isinstance(argument, ast.Constant)
                and type(argument.value) is str
                for argument in node.args
            )
        )
        if not literal_args:
            violations.append(node.lineno)
    return violations


@pytest.mark.parametrize(
    "source",
    (
        'EngineerMessage("X", str(exc))',
        'EngineerMessage("X", f"{exc}")',
        'EngineerMessage("X", "; ".join(errors))',
    ),
)
def test_ast_guard_rejects_exception_and_join_laundering(source):
    assert _engineer_message_constructor_violations(ast.parse(source)) == [1]


def test_production_engineer_messages_are_literal_authored_copy_only():
    root = Path(__file__).resolve().parent.parent
    violations = []
    for folder in (root / "app", root / "sector"):
        for path in folder.rglob("*.py"):
            lines = _engineer_message_constructor_violations(
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            )
            violations.extend(f"{path.relative_to(root)}:{line}" for line in lines)

    assert violations == []
