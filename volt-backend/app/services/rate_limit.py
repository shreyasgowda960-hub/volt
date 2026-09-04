"""Per-IP rate limiting, in process, for the one endpoint that spends money.

This is NOT the rate-limiting spec. It is the smallest thing that has to
exist before spec 014 merges: POST /bookings/estimate is public and
unauthenticated, and since the route cache was removed every call is a live
Google Routes request on the Pro SKU. create_booking recomputes, so a booking
costs two. Nothing else bounds that spend except Google-side quota alerts.

Scope, deliberately narrow:

  * /estimate only. The polling endpoints are untouched — handing a 429 to a
    client that polls every 5s is a different design problem, and it would
    break the exact screen spec 011 exists to keep live.
  * Per IP, not per user: /estimate has no caller identity to key on. That is
    the whole reason it is the endpoint that needs this.
  * In process, no Redis. See the warning on `estimate_limiter` below — this
    is honest at today's scale and only at today's scale.

What this buys and what it does not: 20/min/IP stops a runaway client loop
and raises the cost of casual scripted abuse. It does not bound the bill —
one IP can still spend 1,200 requests an hour. The Google-side per-API daily
quota cap remains the only real ceiling.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

# Chosen from what a real customer can generate, not from a round number.
# One /estimate returns every vehicle option, so comparing bike against
# mini-truck costs zero extra calls — what spends calls is changing pickup,
# drop, the pin or the weight, which is single digits per minute even for a
# fussy customer. The worst legitimate case is a failure during a Render cold
# start: the app's FutureProvider retries twice, so one visible error is three
# requests, and a few Retry taps reach ~12. 20 sits above that and far below
# anything scripted.
ESTIMATE_LIMIT = 20
ESTIMATE_WINDOW_SECONDS = 60.0

# Does not accuse the caller: Indian mobile networks are heavily CGNAT-ed, so
# one public IP is shared by strangers and this may genuinely not be theirs.
_TOO_MANY_DETAIL = (
    "Too many fare requests just now. Please wait a minute and try again."
)


def _now() -> float:
    """Indirection so tests can move time without sleeping.

    Patched at this name, which works only because the call site below is a
    module-global lookup resolved at call time. The same patch aimed at a
    from-imported copy in another module would do nothing — see the routing
    spend-guard note in CLAUDE.md for what that costs when it goes unnoticed.
    """
    return time.monotonic()


@dataclass
class _Window:
    started_at: float
    count: int


class FixedWindowRateLimiter:
    """Fixed window, not sliding.

    A sliding window is more accurate at the edge — a fixed one allows up to
    2x the limit across a boundary (20 at 0:59, 20 more at 1:01). Acceptable
    here: the number exists to stop a runaway loop and to make scripted abuse
    expensive, and one 40-request burst per minute defeats neither. A fixed
    window is a counter and an epoch per key, which is cheaper to hold and far
    easier to reason about.
    """

    def __init__(self, limit: int, window_seconds: float) -> None:
        self._limit = limit
        self._window = window_seconds
        self._windows: dict[str, _Window] = {}
        self._last_prune = 0.0

    def check(self, key: str) -> float | None:
        """Record a hit. None if allowed, else seconds until the window resets."""
        now = _now()
        self._prune(now)

        window = self._windows.get(key)
        if window is None or now - window.started_at >= self._window:
            self._windows[key] = _Window(started_at=now, count=1)
            return None

        if window.count >= self._limit:
            # Deliberately does NOT extend the window, and deliberately does
            # not increment. Being over the limit must not push the reset
            # further out, or a client that keeps retrying — and ours does,
            # the app's FutureProvider retries twice — would lock itself out
            # for as long as it kept trying.
            return self._window - (now - window.started_at)

        window.count += 1
        return None

    def _prune(self, now: float) -> None:
        """Drop expired keys so the dict cannot grow without bound.

        Throttled to once per window rather than run per request: pruning is
        O(keys) and the point of this module is to be cheap. Same shape as the
        expiry sweep's throttle in booking.py, for the same reason.
        """
        if now - self._last_prune < self._window:
            return
        self._last_prune = now
        cutoff = now - self._window
        for key in [k for k, w in self._windows.items() if w.started_at <= cutoff]:
            del self._windows[key]

    def reset(self) -> None:
        """Test hook. Module-level state, so tests must clear it between runs
        or the first test to exhaust a budget fails every later one."""
        self._windows.clear()
        self._last_prune = 0.0


# THIS COUNTER IS PER PROCESS, AND THAT FAILURE IS INVISIBLE.
#
# Render's free plan runs one instance, so today the counter sees every
# request and the limit means what it says. Scale to N instances and each
# keeps its own dict: the effective limit silently becomes 20 x N. Nothing
# errors, no log line appears, and the only symptom is a Google bill. Whoever
# adds a second instance — or a paid plan with autoscaling — has to move this
# to Redis in the same change. That is the rate-limiting spec's job.
estimate_limiter = FixedWindowRateLimiter(ESTIMATE_LIMIT, ESTIMATE_WINDOW_SECONDS)


def reset_rate_limits() -> None:
    """Clear all counters. Used by the autouse test fixture."""
    estimate_limiter.reset()


def client_ip(request: Request) -> str:
    """The address to key on, taken as the LAST X-Forwarded-For entry.

    Not the first. A proxy appends the address it observed to whatever the
    client already sent, so the leftmost entry is caller-controlled: a client
    that sets its own X-Forwarded-For and rotates the value would never be
    limited at all, and would grow the tracking dict by one key per request.
    The rightmost entry is the one our edge actually saw. With exactly one
    trusted proxy in front, that is the real client whether the proxy appends
    to the header or replaces it.

    VERIFY AGAINST RENDER'S OWN DOCS before trusting this in production. If
    there is more than one hop, the rightmost entry is an inner proxy — a
    constant — and every caller would share a single bucket, turning a per-IP
    limit into a global one. The 429 log line records how many entries the
    chain carried, which is enough to settle it from real traffic.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return request.client.host if request.client else "unknown"


async def rate_limit_estimate(request: Request) -> None:
    """Route dependency. Raises 429 in the app's standard error shape."""
    key = client_ip(request)
    retry_after = estimate_limiter.check(key)
    if retry_after is None:
        return

    chain = request.headers.get("x-forwarded-for", "")
    # WARNING, not INFO: at 20/min this should be rare, and when it stops
    # being rare it is either a client bug or someone spending our budget.
    logger.warning(
        "rate limit hit on /estimate: ip=%s xff_entries=%d retry_after=%.0fs",
        key,
        len([p for p in chain.split(",") if p.strip()]),
        retry_after,
    )
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=_TOO_MANY_DETAIL,
        headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
    )
