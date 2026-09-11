"""Bounded real-time wait for an issuer-advertised OAuth expiry."""

import asyncio
import math
import time
from collections.abc import Awaitable, Callable


async def wait_for_expiry(
    expiry: float | None,
    max_wait: int,
    report: Callable[[int], None],
    *,
    clock: Callable[[], float] = time.time,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    if expiry is None or not math.isfinite(expiry) or not 0 < max_wait <= 86400:
        raise ValueError("MCP_EXPIRY_EVIDENCE_UNAVAILABLE")
    remaining = expiry + 2 - clock()
    if not 0 < remaining <= max_wait:
        raise ValueError("MCP_EXPIRY_OUTSIDE_WAIT_BOUND")
    deadline = monotonic() + max_wait
    while (remaining := expiry + 2 - clock()) > 0:
        if monotonic() >= deadline:
            raise ValueError("MCP_EXPIRY_WAIT_DEADLINE")
        report(math.ceil(remaining))
        await sleep(min(30, remaining, deadline - monotonic()))
