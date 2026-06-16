"""Character-set helpers for bulk 3-character nickname scanning.

CONTRACT:
    def iter_letter_nicknames(length: int = 3) -> Iterator[str]   # aaa..zzz
    def iter_digit_nicknames(length: int = 3) -> Iterator[str]    # 000..999
    def count_letter(length: int = 3) -> int                      # 26 ** length
    def count_digit(length: int = 3) -> int                       # 10 ** length

The generators emit every combination in lexical order so the scan is
deterministic and resumable. They are lazy (``itertools.product``) so we never
materialise the full 17576-entry letter space in memory.
"""
from __future__ import annotations

import string
from collections.abc import Iterator
from itertools import product

LETTERS = string.ascii_lowercase  # a-z
DIGITS = string.digits  # 0-9


def iter_letter_nicknames(length: int = 3) -> Iterator[str]:
    """Yield 'aaa'..'zzz' over lowercase a-z (26 ** length combinations)."""
    for combo in product(LETTERS, repeat=length):
        yield "".join(combo)


def iter_digit_nicknames(length: int = 3) -> Iterator[str]:
    """Yield '000'..'999' over 0-9 (10 ** length combinations)."""
    for combo in product(DIGITS, repeat=length):
        yield "".join(combo)


def count_letter(length: int = 3) -> int:
    """Number of lowercase-letter combinations of the given length."""
    return len(LETTERS) ** length


def count_digit(length: int = 3) -> int:
    """Number of digit combinations of the given length."""
    return len(DIGITS) ** length
