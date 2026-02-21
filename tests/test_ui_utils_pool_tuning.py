from __future__ import annotations

import pytest
from src.utils import compute_adaptive_pool_limit, compute_exponential_moving_average


@pytest.mark.smoke
def test_compute_adaptive_pool_limit_grows_when_hit_rate_low() -> None:
    new_size = compute_adaptive_pool_limit(
        current=300,
        min_size=150,
        cap_size=1200,
        step=50,
        pool_len=260,
        hit_rate=20.0,
    )
    assert new_size == 350


@pytest.mark.smoke
def test_compute_adaptive_pool_limit_shrinks_when_hit_rate_high_and_pool_idle() -> None:
    new_size = compute_adaptive_pool_limit(
        current=300,
        min_size=150,
        cap_size=1200,
        step=50,
        pool_len=40,
        hit_rate=95.0,
    )
    assert new_size == 250


@pytest.mark.smoke
def test_compute_exponential_moving_average_uses_previous_value() -> None:
    ema = compute_exponential_moving_average(previous=80.0, current=20.0, alpha=0.25)
    assert ema == pytest.approx(65.0)


@pytest.mark.smoke
def test_compute_exponential_moving_average_first_sample_returns_current() -> None:
    ema = compute_exponential_moving_average(previous=None, current=33.0, alpha=0.25)
    assert ema == pytest.approx(33.0)
