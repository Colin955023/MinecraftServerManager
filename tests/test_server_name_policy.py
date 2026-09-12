from __future__ import annotations

import pytest

from src.utils import MAX_SERVER_NAME_LENGTH, validate_server_name


def test_validate_server_name_accepts_normal_unicode_name() -> None:
    assert validate_server_name("生存伺服器 26.2") == "生存伺服器 26.2"


@pytest.mark.parametrize(
    "name",
    [
        "",
        " demo",
        "demo ",
        ".",
        "..",
        "a/b",
        r"a\b",
        "bad:name",
        "bad?name",
        "bad<name",
        "bad>name",
        'bad"name',
        "bad|name",
        "bad*name",
        "demo.",
        ".msm-delete-test",
        "servers_config.json",
        "CON",
        "con.txt",
        "CONIN$",
        "CONOUT$.log",
        "CLOCK$",
        "CLOCK$.log",
        "CON .txt",
        "COM1 .txt",
        "LPT1",
        "COM9.log",
        "COM¹",
    ],
)
def test_validate_server_name_rejects_unsafe_or_reserved_names(name: str) -> None:
    with pytest.raises(ValueError):
        validate_server_name(name)


def test_validate_server_name_enforces_shared_length_limit() -> None:
    assert len("a" * MAX_SERVER_NAME_LENGTH) == MAX_SERVER_NAME_LENGTH
    assert validate_server_name("a" * MAX_SERVER_NAME_LENGTH) == "a" * MAX_SERVER_NAME_LENGTH
    with pytest.raises(ValueError):
        validate_server_name("a" * (MAX_SERVER_NAME_LENGTH + 1))
