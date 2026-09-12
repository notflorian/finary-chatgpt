"""Credential-free regression for bounded natural-expiry waiting."""

import asyncio

import pytest
from mcp_live_expiry import wait_for_expiry


def test_natural_expiry_wait_uses_real_deadline_and_bounded_intervals():
    now = [100.0]
    intervals = []
    reports = []

    async def sleep(seconds):
        intervals.append(seconds)
        now[0] += seconds

    asyncio.run(
        wait_for_expiry(
            165, 100, reports.append, clock=lambda: now[0], monotonic=lambda: now[0], sleep=sleep
        )
    )
    assert now[0] == 167
    assert intervals == [30, 30, 7]
    assert reports == [67, 37, 7]


@pytest.mark.parametrize("expiry", [None, float("inf"), float("nan"), 50, 10000])
def test_unknown_expired_or_excessive_lifetime_is_not_success(expiry):
    with pytest.raises(ValueError, match="MCP_EXPIRY_"):
        asyncio.run(wait_for_expiry(expiry, 100, lambda _: None, clock=lambda: 100))


def test_wall_clock_jump_cannot_extend_monotonic_wait_bound():
    elapsed = [0.0]

    async def sleep(seconds):
        elapsed[0] += seconds

    with pytest.raises(ValueError, match="MCP_EXPIRY_WAIT_DEADLINE"):
        asyncio.run(
            wait_for_expiry(
                105,
                10,
                lambda _: None,
                clock=lambda: 100,
                monotonic=lambda: elapsed[0],
                sleep=sleep,
            )
        )
    assert elapsed[0] == 10
