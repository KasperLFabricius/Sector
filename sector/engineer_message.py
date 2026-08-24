"""Typed, authored copy that may be shown to an engineer.

The type carries no presentation behaviour. Publication policy belongs to
``app.engineer_messages`` so headless calculation modules can attach deliberate
engineering guidance to an exception without depending on the application.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_CODE = re.compile(r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*\Z")


@dataclass(frozen=True, slots=True)
class EngineerMessage:
    """One immutable, explicitly authored engineer-facing message."""

    code: str
    text: str

    def __post_init__(self) -> None:
        if type(self.code) is not str or _CODE.fullmatch(self.code) is None:
            raise ValueError(
                "EngineerMessage code must be an uppercase hyphenated identifier"
            )
        if (
            type(self.text) is not str
            or not self.text
            or self.text != self.text.strip()
            or any(character in self.text for character in "\r\n")
        ):
            raise ValueError(
                "EngineerMessage text must be non-empty, trimmed single-line copy"
            )
