"""The rate limit on POST /bookings/estimate.

Every test here keys on its own X-Forwarded-For value. Sharing one key across
tests would make them order-dependent in exactly the way the autouse reset in
conftest exists to prevent — and would hide a reset bug rather than catch it.
"""

import logging
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.rate_limit import (
    ESTIMATE_LIMIT,
    ESTIMATE_WINDOW_SECONDS,
    FixedWindowRateLimiter,
    client_ip,
)

# The two trusted hops in front of us, from the chain measured against
# production on 2026-09-05. Tests must send a realistic three-entry chain or
# they exercise the fallback path instead of the real one — which is how the
# previous version of this file passed while the limiter was globally bucketed.
_CLOUDFLARE = "172.69.123.178"
_RENDER_INTERNAL = "10.199.202.132"

# Client addresses in these tests must be GLOBALLY ROUTABLE. The obvious
# choice — the TEST-NET-3 documentation range, 203.0.113.0/24 — is classified
# reserved by ipaddress, so client_ip's proxy guard would reject every one of
# them and fall back to the leftmost entry. These are real-looking Indian
# mobile addresses for that reason; do not "tidy" them back to TEST-NET.


def _chain(client: str, *prepended: str) -> str:
    """An X-Forwarded-For shaped the way production actually produces it.

    `prepended` simulates a client that sends its own header: trusted hops
    append after it, so those entries land on the LEFT of the real address.
    """
    return ", ".join([*prepended, client, _CLOUDFLARE, _RENDER_INTERNAL])

# Inside the default 25km service area, so nothing here is refused for a
# reason that has nothing to do with rate limiting.
_PICKUP = (12.9716, 77.5946)
_DROP = (13.0250, 77.5946)


def _payload() -> dict:
    return {
        "pickup": {"address": "Pickup", "lat": _PICKUP[0], "lng": _PICKUP[1]},
        "drop": {"address": "Drop", "lat": _DROP[0], "lng": _DROP[1]},
    }


def _client(ip: str, *prepended: str) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Forwarded-For": _chain(ip, *prepended)},
    )


# --- Through the endpoint -------------------------------------------------


@pytest.mark.asyncio
async def test_requests_up_to_the_limit_all_pass():
    async with _client("106.222.200.10") as client:
        for i in range(ESTIMATE_LIMIT):
            resp = await client.post("/api/v1/bookings/estimate", json=_payload())
            assert resp.status_code == 200, f"request {i + 1} was rejected"
            assert resp.json()["options"], "a 200 must still carry real fares"


@pytest.mark.asyncio
async def test_request_over_the_limit_returns_429():
    async with _client("106.222.200.11") as client:
        for _ in range(ESTIMATE_LIMIT):
            assert (
                await client.post("/api/v1/bookings/estimate", json=_payload())
            ).status_code == 200

        resp = await client.post("/api/v1/bookings/estimate", json=_payload())

    assert resp.status_code == 429
    # The app's one error shape, same as every other refusal.
    assert "try again" in resp.json()["detail"]
    # Tells a client how long to wait instead of making it guess.
    assert 0 < int(resp.headers["retry-after"]) <= ESTIMATE_WINDOW_SECONDS


@pytest.mark.asyncio
async def test_window_resets():
    ip = "106.222.200.12"
    base = 1000.0
    clock = {"t": base}

    with patch("app.services.rate_limit._now", lambda: clock["t"]):
        async with _client(ip) as client:
            for _ in range(ESTIMATE_LIMIT):
                await client.post("/api/v1/bookings/estimate", json=_payload())

            blocked = await client.post("/api/v1/bookings/estimate", json=_payload())
            assert blocked.status_code == 429

            # Still inside the window: a caller cannot wait its way out early.
            clock["t"] = base + ESTIMATE_WINDOW_SECONDS - 0.5
            still_blocked = await client.post(
                "/api/v1/bookings/estimate", json=_payload()
            )
            assert still_blocked.status_code == 429

            clock["t"] = base + ESTIMATE_WINDOW_SECONDS + 0.1
            allowed = await client.post("/api/v1/bookings/estimate", json=_payload())
            assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_limit_does_not_apply_to_other_endpoints():
    """The limiter is attached to one route, not to the app.

    This is the check that would fail if someone ever "tidied" it into
    middleware: the polling endpoints must never 429, or a live booking
    screen goes blank mid-trip.
    """
    ip = "106.222.200.13"
    async with _client(ip) as client:
        for _ in range(ESTIMATE_LIMIT):
            await client.post("/api/v1/bookings/estimate", json=_payload())
        assert (
            await client.post("/api/v1/bookings/estimate", json=_payload())
        ).status_code == 429

        # Same IP, same exhausted budget, different routes.
        for _ in range(ESTIMATE_LIMIT + 5):
            assert (await client.get("/api/v1/vehicle-types")).status_code == 200
            assert (await client.get("/api/v1/service-area")).status_code == 200


@pytest.mark.asyncio
async def test_one_ip_being_limited_does_not_limit_another():
    """Proves the counter is actually keyed, rather than globally counting.

    Without this, a limiter that ignored its key entirely would pass every
    other test in this file.
    """
    async with _client("106.222.200.14") as noisy:
        for _ in range(ESTIMATE_LIMIT):
            await noisy.post("/api/v1/bookings/estimate", json=_payload())
        assert (
            await noisy.post("/api/v1/bookings/estimate", json=_payload())
        ).status_code == 429

    async with _client("106.222.200.15") as innocent:
        resp = await innocent.post("/api/v1/bookings/estimate", json=_payload())
    assert resp.status_code == 200


# --- The key itself -------------------------------------------------------


class _FakeRequest:
    def __init__(self, headers: dict, client=None) -> None:
        self.headers = headers
        self.client = client


class _Peer:
    def __init__(self, host: str) -> None:
        self.host = host


def test_three_entry_chain_resolves_to_the_client():
    """The measured production shape: client, Cloudflare, Render internal."""
    request = _FakeRequest({"x-forwarded-for": _chain("106.222.200.144")})
    assert client_ip(request) == "106.222.200.144"


def test_prepended_spoof_entries_resolve_to_the_same_address():
    """A client sending its own X-Forwarded-For lands on the LEFT of the real
    address, because trusted hops append. Counting from the right is what
    makes prepending pointless — assert that directly, with chains of three
    different lengths that must all produce one key."""
    plain = _FakeRequest({"x-forwarded-for": _chain("106.222.200.144")})
    one_spoof = _FakeRequest(
        {"x-forwarded-for": _chain("106.222.200.144", "1.2.3.4")}
    )
    many_spoofs = _FakeRequest(
        {
            "x-forwarded-for": _chain(
                "106.222.200.144", "1.2.3.4", "5.6.7.8", "9.10.11.12"
            )
        }
    )

    assert (
        client_ip(plain)
        == client_ip(one_spoof)
        == client_ip(many_spoofs)
        == "106.222.200.144"
    )


def test_short_chain_falls_back_to_the_leftmost_entry_and_warns(caplog):
    """Fewer entries than trusted hops means a hop was removed — a client
    cannot cause it, since prepending only lengthens the chain.

    The leftmost entry is the real client in every 'hop disappeared'
    topology, so limiting keeps working; the warning is what makes the
    change visible rather than silent.
    """
    with caplog.at_level(logging.WARNING, logger="app.services.rate_limit"):
        two_hops = _FakeRequest(
            {"x-forwarded-for": f"106.222.200.144, {_RENDER_INTERNAL}"}
        )
        assert client_ip(two_hops) == "106.222.200.144"

        one_hop = _FakeRequest({"x-forwarded-for": "106.222.200.144"})
        assert client_ip(one_hop) == "106.222.200.144"

    assert len(caplog.records) == 2
    # The warning has to name the actual chain, or nobody can tell what the
    # new topology is without reproducing it.
    assert _RENDER_INTERNAL in caplog.records[0].getMessage()
    assert "topology has changed" in caplog.records[0].getMessage()


def test_no_forwarded_header_uses_the_peer_and_does_not_warn(caplog):
    """Local development and the test suite have no proxy in front. That is
    not a topology change, so warning there would be noise that trains
    everyone to ignore the warning that matters."""
    with caplog.at_level(logging.WARNING, logger="app.services.rate_limit"):
        assert client_ip(_FakeRequest({}, client=_Peer("198.51.100.9"))) == (
            "198.51.100.9"
        )
        assert client_ip(_FakeRequest({}, client=None)) == "unknown"

    assert caplog.records == []


def test_extra_internal_hops_trigger_the_guard(caplog):
    """A hop added inside our infrastructure pushes -3 onto a private address.

    An address in 10/8 cannot be a client that reached us over the internet,
    so resolving to one proves the index is wrong. Without the guard every
    request resolves to the same internal address and shares one bucket —
    the original global-bucket bug arriving by a different door.
    """
    chain = ", ".join(
        [
            "106.222.200.144",  # real client
            _CLOUDFLARE,
            "10.199.202.132",  # Render internal
            "10.199.202.7",  # added internal hop
            "10.199.202.9",  # added internal hop
        ]
    )
    with caplog.at_level(logging.ERROR, logger="app.services.rate_limit"):
        assert client_ip(_FakeRequest({"x-forwarded-for": chain})) == "106.222.200.144"

    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "10.199.202.132" in message, "must name the address it resolved to"
    assert chain in message, "must name the full chain, or nobody can re-measure"


def test_a_single_added_internal_hop_is_not_caught():
    """Records a KNOWN LIMITATION rather than asserting good behaviour.

    Hops append at the tail, so k added hops put index -3 at position k:
    with exactly one added hop, -3 lands on Cloudflare's own address, which
    is public and therefore passes the guard. The limiter silently keys on a
    constant again.

    This test exists so the gap is discovered by reading the suite rather
    than by reading a Google bill. If someone fixes it, this test fails and
    points them at the docs to update.
    """
    chain = ", ".join(
        ["106.222.200.144", _CLOUDFLARE, "10.199.202.132", "10.199.202.7"]
    )
    assert client_ip(_FakeRequest({"x-forwarded-for": chain})) == _CLOUDFLARE


def test_normal_chain_does_not_trigger_the_guard(caplog):
    """The measured production shape must stay silent, or the error becomes
    noise that everyone learns to scroll past."""
    with caplog.at_level(logging.ERROR, logger="app.services.rate_limit"):
        assert client_ip(
            _FakeRequest({"x-forwarded-for": _chain("106.222.200.144")})
        ) == "106.222.200.144"

    assert caplog.records == []


@pytest.mark.parametrize(
    "reserved",
    [
        # --- reserved ranges: an added internal hop ------------------------
        "fd00::1",  # unique local (IPv6 private)
        "fe80::1",  # link-local
        "::1",  # loopback
        "10.199.202.132",  # IPv4 private
        "127.0.0.1",  # IPv4 loopback
        "169.254.1.1",  # IPv4 link-local
        "2001:db8::1",  # IPv6 documentation range
        # --- not addresses at all: malformed or obfuscated -----------------
        # Everything below arrives from a real client or a misbehaving proxy
        # rather than from a topology change, and none of it may raise.
        "not-an-ip-address",
        "unknown",  # RFC 7239 permits this literal token
        "_hidden",  # RFC 7239 obfuscated identifier
        "proxy.example.com",  # a hostname, not an address
        "1.2.3.4:5678",  # v4 with a port
        "[2001:db8::1]:443",  # v6 bracketed with a port
        "010.1.1.1",  # leading zeros: rejected since Python 3.9
        "0x7f.0.0.1",  # hex octet
        "1.2.3",  # too few octets
        "1.2.3.4.5",  # too many octets
        "-1.2.3.4",  # negative octet
        "999999999999999999999",  # bare huge integer
        "9" * 2000,  # absurdly long single entry
        "१०६.२२",  # non-ASCII digits
        "106.222.200.144​",  # a real address with a zero-width space
    ],
)
def test_guard_fires_on_every_reserved_range(reserved, caplog):
    """IPv6 included: an internal hop is as likely to be fd00::/8 as 10/8,
    and a v4-only check would pass it straight through.

    The malformed half of this list is not about topology at all — it is
    parsing. ipaddress.ip_address raises ValueError on every one of them, and
    an uncaught ValueError here would 500 a public endpoint on input a caller
    fully controls.
    """
    # Five entries, so index -3 is the parametrized one. Four would put -3 on
    # Cloudflare instead — the single-added-hop blind spot recorded above.
    chain = (
        f"106.222.200.144, {_CLOUDFLARE}, {reserved}, 10.199.202.7, 10.199.202.9"
    )
    with caplog.at_level(logging.ERROR, logger="app.services.rate_limit"):
        assert client_ip(_FakeRequest({"x-forwarded-for": chain})) == "106.222.200.144"

    assert len(caplog.records) == 1


@pytest.mark.parametrize(
    "header",
    [",", " , , ", ",,,", " ", "", "\t", ",".join([" "] * 300)],
)
def test_separator_only_header_falls_back_to_the_peer(header, caplog):
    """A header of nothing but separators is TRUTHY but yields no entries.

    That combination used to sail past a `not forwarded` gate and reach
    parts[0] at the bottom of client_ip, raising IndexError — a 500 on a
    public endpoint, from a header any caller can send. It is now handled by
    the same branch as a missing header: the peer socket, and no warning,
    because a malformed header is not evidence the topology changed.
    """
    with caplog.at_level(logging.WARNING, logger="app.services.rate_limit"):
        request = _FakeRequest(
            {"x-forwarded-for": header}, client=_Peer("198.51.100.9")
        )
        assert client_ip(request) == "198.51.100.9"

    assert caplog.records == []


def test_blank_entries_between_real_ones_are_ignored():
    """Blanks are filtered before indexing, so they cannot shift -3.

    This matters because a client CAN inject them: anything it prepends is
    followed by the three real hops, so filtering has to leave the tail
    alignment intact.
    """
    padded = f" , {'106.222.200.144'}, , {_CLOUDFLARE}, , {_RENDER_INTERNAL}, "
    assert client_ip(_FakeRequest({"x-forwarded-for": padded})) == "106.222.200.144"


@pytest.mark.parametrize("depth", [50, 300, 1000])
def test_a_long_prepended_chain_still_resolves_to_the_client(depth):
    """Counting from the right is supposed to be indifferent to chain length.

    A client can prepend as many entries as the HTTP layer's header size
    limit allows; none of them may move the resolved address or cost anything
    that scales badly.
    """
    chain = ", ".join(["1.2.3.4"] * depth + ["106.222.200.144", _CLOUDFLARE, _RENDER_INTERNAL])
    assert client_ip(_FakeRequest({"x-forwarded-for": chain})) == "106.222.200.144"


@pytest.mark.asyncio
async def test_spoofed_entries_cannot_escape_an_exhausted_budget():
    """The security property, end to end rather than on the helper.

    Exhaust the budget as a normal client, then come back prepending fake
    entries — the thing an attacker would actually try. It must still be 429.
    """
    ip = "106.222.200.16"
    async with _client(ip) as client:
        for _ in range(ESTIMATE_LIMIT):
            await client.post("/api/v1/bookings/estimate", json=_payload())

    async with _client(ip, "1.2.3.4", "5.6.7.8") as spoofer:
        resp = await spoofer.post("/api/v1/bookings/estimate", json=_payload())
    assert resp.status_code == 429


# --- The counter itself ---------------------------------------------------


def test_being_over_the_limit_does_not_extend_the_window():
    """A blocked caller that keeps hammering must still be released on time.

    The app's own FutureProvider retries twice on failure, so this is the
    behaviour of a normal client, not an attacker.
    """
    clock = {"t": 500.0}
    limiter = FixedWindowRateLimiter(limit=2, window_seconds=60.0)

    with patch("app.services.rate_limit._now", lambda: clock["t"]):
        assert limiter.check("k") is None
        assert limiter.check("k") is None
        assert limiter.check("k") is not None

        # Hammer for most of the window.
        for offset in (10.0, 20.0, 30.0, 59.0):
            clock["t"] = 500.0 + offset
            assert limiter.check("k") is not None

        clock["t"] = 500.0 + 60.0
        assert limiter.check("k") is None, "the window should have reset on time"


def test_expired_keys_are_pruned():
    """Otherwise the dict is an unbounded memory leak on a long-lived process."""
    clock = {"t": 0.0}
    limiter = FixedWindowRateLimiter(limit=5, window_seconds=60.0)

    with patch("app.services.rate_limit._now", lambda: clock["t"]):
        for i in range(50):
            clock["t"] = float(i)
            limiter.check(f"ip-{i}")

        assert len(limiter._windows) == 50

        # Well past every window above, and past the prune throttle.
        clock["t"] = 1000.0
        limiter.check("fresh")

    assert list(limiter._windows) == ["fresh"]
