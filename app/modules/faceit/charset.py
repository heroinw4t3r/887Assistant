"""Character-set helpers for bulk 3-character nickname scanning.

CONTRACT:
    def iter_letter_nicknames(length: int = 3) -> Iterator[str]   # aaa..zzz
    def iter_digit_nicknames(length: int = 3) -> Iterator[str]    # 000..999

TODO(subagent-4): implement generators (and any FACEIT nickname validation).
"""
from __future__ import annotations
