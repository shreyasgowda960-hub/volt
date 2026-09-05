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

Resolving the client address
----------------------------
Everything above depends on keying each caller separately, and getting that
wrong is silent. Measured against production on 2026-09-05 from a real
device, the chain is three trusted hops:

    106.222.200.144, 172.69.123.178, 10.199.202.132
    └ real client      └ Cloudflare    └ Render internal

Trusted hops APPEND the address they observed, so the count is stable from
the right and unstable from the left. Index -3 is therefore the address
Cloudflare observed, regardless of how many entries a client prepends —
prepending only lengthens the chain and shifts nothing at the tail.

Both simpler choices are wrong. The FIRST entry is caller-supplied, so a
client that rotates a fake value is never limited. The LAST entry is Render's
internal proxy, identical on every request — that was the original
implementation, and it made the limiter global instead of per-IP.
"""

from __future__ import annotations

import ipaddress
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

# Trusted hops between a real client and this process: Cloudflare, then
# Render's internal proxy, appended in that order after the client's own
# address. Measured, not assumed — see the module docstring. This is the one
# number to change if the infrastructure in front of us ever does.
_TRUSTED_HOPS = 3

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


def _is_usable_client_address(value: str) -> bool:
    """False for anything that cannot be a real client's address.

    `is_global` is the single check that covers the whole set at once:
    private (10/8, 172.16/12, 192.168/16, IPv6 fc00::/7), loopback,
    link-local (169.254/16, fe80::/10), CGNAT shared space, multicast and the
    reserved/documentation ranges. Note that a CUSTOMER behind carrier NAT
    still presents a global address here — the carrier's public egress is
    what Cloudflare observes, not the 100.64/10 address inside their network.

    An unparseable value fails too. X-Forwarded-For may legally carry
    obfuscated identifiers, and a caller can put arbitrary junk there; either
    way it is not the address this function measured, so it is treated the
    same as a proxy address rather than silently becoming a bucket key.
    """
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


def client_ip(request: Request) -> str:
    """The address to key on: the THIRD X-Forwarded-For entry from the right.

    Measured against production on 2026-09-05, from a real device:

        106.222.200.144, 172.69.123.178, 10.199.202.132
        └ real client      └ Cloudflare    └ Render internal

    Three trusted hops, each appending the address it observed to the end of
    whatever it received. So counting from the right is what makes this
    stable: index -3 is the address Cloudflare saw, no matter how many
    entries a client prepends. A client that sends its own X-Forwarded-For
    only makes the chain longer — "spoof, client, CF, render" still resolves
    to the client at -3 — which is why prepending buys nothing.

    The two obvious alternatives are both wrong, and were both tried:

      * index 0 is whatever the caller sent. A client that rotates a fake
        leftmost value would never be limited, and would grow the tracking
        dict by one key per request.
      * index -1 is Render's internal proxy address, which is IDENTICAL on
        every request. That was the previous implementation, and it made the
        limiter global rather than per-IP — 20/min shared by every customer
        in the country. It looked correct and was not.

    THIS IS PINNED TO SOMEONE ELSE'S TOPOLOGY. Add, remove or reorder a hop —
    drop Cloudflare, put a WAF in front, change hosting — and -3 silently
    names the wrong thing. Two of the three directions are guarded:

      * a hop REMOVED shortens the chain below _TRUSTED_HOPS, which a client
        cannot cause. Warns, then falls back to the leftmost entry.
      * a hop ADDED can push -3 onto an internal address. That is caught by
        _is_usable_client_address: a private, loopback, link-local or
        otherwise reserved address cannot be a real client arriving over the
        internet, so resolving to one proves the index is wrong.
      * a PUBLIC hop added is NOT caught, and cannot be from inside a single
        request — a WAF's public address is indistinguishable from a
        customer's. Note this includes the case of exactly ONE added internal
        hop, where -3 lands on Cloudflare's own public address. Re-measure
        the chain after any infrastructure change.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        # No proxy in front at all: local development, or the test suite.
        # Not a topology change, so not worth a warning — the peer socket is
        # genuinely the client here.
        return request.client.host if request.client else "unknown"

    parts = [p.strip() for p in forwarded.split(",") if p.strip()]

    if len(parts) >= _TRUSTED_HOPS:
        resolved = parts[-_TRUSTED_HOPS]
        if _is_usable_client_address(resolved):
            return resolved

        # A private, loopback, link-local or reserved address at -3 cannot be
        # a client that reached us over the internet. It is a proxy — so a hop
        # has been added and the index is now pointing inside our own
        # infrastructure. Left alone, every request would resolve to the same
        # internal address and share one bucket: the original bug, returning
        # by a different door.
        #
        # ERROR rather than WARNING because unlike a shortened chain this is
        # not a benign degradation — it means the limiter has silently stopped
        # being per-IP, and somebody has to re-measure and move _TRUSTED_HOPS.
        logger.error(
            "X-Forwarded-For resolved to %s, which cannot be a public client "
            "address — a proxy hop has been added and _TRUSTED_HOPS=%d is now "
            "wrong. Falling back to the leftmost entry, which is "
            "caller-supplied. Re-measure the chain. Chain was: %s",
            resolved,
            _TRUSTED_HOPS,
            forwarded,
        )
        return parts[0]

    # Fewer entries than there are trusted hops. A client cannot cause this —
    # prepending makes the chain longer, never shorter — so it means a hop was
    # REMOVED and the assumption above no longer holds.
    #
    # Falls back to the leftmost entry rather than failing the request or
    # falling through to the peer socket. In every "a hop disappeared"
    # topology the leftmost entry is the real client again, so ordinary
    # per-IP limiting keeps working while the shape is wrong. The peer socket
    # would be Render's proxy — one global bucket, the exact bug this
    # function was rewritten to fix — and refusing the request would turn
    # someone else's config change into a total outage of fare estimates.
    #
    # Degrading to "spoofable" is the accepted cost: a spoofer is still
    # bounded by the Google-side quota cap, which is the real ceiling anyway.
    logger.warning(
        "X-Forwarded-For has %d entries, expected at least %d — proxy "
        "topology has changed and the rate limiter is keying on the leftmost "
        "entry, which is caller-supplied. Re-measure the chain. Chain was: %s",
        len(parts),
        _TRUSTED_HOPS,
        forwarded,
    )
    return parts[0]


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
