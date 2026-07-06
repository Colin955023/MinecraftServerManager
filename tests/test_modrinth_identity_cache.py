from __future__ import annotations

from typing import Any, cast

import pytest
from src.core.mod_models import ModrinthIdentityCache


class _SpyLock:
    def __init__(self) -> None:
        self.entered = False
        self.exited = False

    def __enter__(self) -> _SpyLock:
        self.entered = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.exited = True


def test_modrinth_identity_cache_rejects_negative_max_size() -> None:
    with pytest.raises(ValueError, match="max_size must be >= 0"):
        ModrinthIdentityCache(max_size=-1)


def test_modrinth_identity_cache_len_uses_lock() -> None:
    cache = ModrinthIdentityCache()
    spy_lock = _SpyLock()
    cast(Any, cache)._lock = spy_lock
    cache.set("example", ("project-id", "slug"))

    assert len(cache) == 1
    assert spy_lock.entered is True
    assert spy_lock.exited is True
