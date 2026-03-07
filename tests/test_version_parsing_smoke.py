from __future__ import annotations

import pytest
from packaging.version import Version
from src.utils import UpdateParsing


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("version_str", "expected"),
    [
        ("v1.6.6", Version("1.6.6")),
        ("1.7.0-beta.1", Version("1.7.0b1")),
        ("  V2.0.1+build7  ", Version("2.0.1+build7")),
        ("1", Version("1")),
    ],
)
def test_parse_version_valid(version_str: str, expected: Version) -> None:
    assert UpdateParsing.parse_version(version_str) == expected


@pytest.mark.smoke
@pytest.mark.parametrize("version_str", ["", "  ", "abc", "version-x.y.z", None])
def test_parse_version_invalid(version_str: str | None) -> None:
    assert UpdateParsing.parse_version(version_str) is None
