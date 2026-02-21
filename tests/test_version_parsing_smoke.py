from __future__ import annotations

import pytest
from src.utils import UpdateParsing


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("version_str", "expected"),
    [
        ("v1.6.6", (1, 6, 6)),
        ("1.7.0-beta.1", (1, 7, 0)),
        ("  V2.0.1+build7  ", (2, 0, 1)),
        ("1", (1,)),
    ],
)
def test_parse_version_valid(version_str: str, expected: tuple[int, ...]) -> None:
    assert UpdateParsing.parse_version(version_str) == expected


@pytest.mark.smoke
@pytest.mark.parametrize("version_str", ["", "  ", "abc", "version-x.y.z", None])
def test_parse_version_invalid(version_str: str | None) -> None:
    assert UpdateParsing.parse_version(version_str) is None
