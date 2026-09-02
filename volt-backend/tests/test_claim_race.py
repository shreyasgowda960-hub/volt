import asyncio
import time

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models.booking import Booking, BookingStatus
from app.models.driver import Driver
from app.models.user import User
from app.schemas.booking import BookingCreate, LocationIn
from app.services.booking import claim_booking, create_booking
from app.services.booking_lifecycle import BookingAlreadyClaimed, DriverHasActiveBooking

_PICKUP = LocationIn(address="Koramangala", lat=12.9352, lng=77.6245)
_DROP = LocationIn(address="Whitefield", lat=12.9698, lng=77.75)


async def _cleanup(phone_customer: str, phone_a: str, phone_b: str) -> None:
    async with SessionLocal() as db:
        # Bookings reference both users.id and drivers.id; must go first or
        # the FK blocks deleting whichever row it still points to.
        user_id = (
            await db.execute(select(User.id).where(User.phone == phone_customer))
        ).scalar_one_or_none()
        if user_id is not None:
            await db.execute(delete(Booking).where(Booking.customer_id == user_id))
            await db.execute(delete(User).where(User.id == user_id))
        await db.execute(delete(Driver).where(Driver.phone.in_([phone_a, phone_b])))
        await db.commit()


@pytest.mark.asyncio
async def test_two_concurrent_accepts_exactly_one_wins():
    """The race, tested for real: two independent DB sessions (independent
    asyncpg connections) both call claim_booking() on the same row via
    asyncio.gather, so the interleaving is driven by real network I/O
    round-trips through asyncpg — not by the test manually simulating one.

    Whichever UPDATE reaches Postgres second blocks on the winner's row lock,
    then (under READ COMMITTED) re-evaluates its WHERE clause against the
    now-committed row and matches nothing — which is exactly the mechanism
    claim_booking's docstring describes, not a weaker approximation of it.
    """
    phone_customer = "+919000006001"
    phone_a = "+919000006002"
    phone_b = "+919000006003"
    await _cleanup(phone_customer, phone_a, phone_b)

    async with SessionLocal() as setup_db:
        customer = User(phone=phone_customer)
        setup_db.add(customer)
        await setup_db.commit()
        await setup_db.refresh(customer)

        booking = await create_booking(
            setup_db,
            BookingCreate(
                pickup=_PICKUP,
                drop=_DROP,
                vehicle_type_code="bike",
                goods_description="Race test parcel",
                approx_weight_kg=5,
            ),
            customer,
        )
        public_code = booking.public_code

        driver_a = Driver(
            phone=phone_a,
            name="Driver A",
            vehicle_number="KA 05 AB 1111",
            vehicle_type_code="bike",
            is_online=True,
            is_verified=True,
        )
        driver_b = Driver(
            phone=phone_b,
            name="Driver B",
            vehicle_number="KA 05 AB 2222",
            vehicle_type_code="bike",
            is_online=True,
            is_verified=True,
        )
        setup_db.add_all([driver_a, driver_b])
        await setup_db.commit()
        await setup_db.refresh(driver_a)
        await setup_db.refresh(driver_b)

    # Two separate sessions -> two separate asyncpg connections -> genuine
    # concurrent transactions against the same row.
    async with SessionLocal() as db_a, SessionLocal() as db_b:
        results = await asyncio.gather(
            claim_booking(db_a, public_code, driver_a),
            claim_booking(db_b, public_code, driver_b),
            return_exceptions=True,
        )

    successes = [r for r in results if isinstance(r, Booking)]
    failures = [r for r in results if isinstance(r, BaseException)]

    assert len(successes) == 1, (
        f"expected exactly one winner, got {len(successes)}: {results}"
    )
    assert len(failures) == 1
    assert isinstance(failures[0], BookingAlreadyClaimed)

    winner = successes[0]
    assert winner.status == BookingStatus.driver_assigned
    assert winner.driver_id in (driver_a.id, driver_b.id)

    async with SessionLocal() as verify_db:
        result = await verify_db.execute(
            delete(Booking).where(Booking.public_code == public_code).returning(
                Booking.driver_id, Booking.status
            )
        )
        row = result.first()
        await verify_db.commit()

    assert row is not None
    assert row.driver_id == winner.driver_id
    assert row.status == BookingStatus.driver_assigned

    await _cleanup(phone_customer, phone_a, phone_b)


@pytest.mark.asyncio
async def test_losing_update_genuinely_blocks_on_the_winners_row_lock():
    """The test above proves the *outcome* is correct under asyncio.gather,
    but in one observed run the loser's UPDATE didn't fire until after the
    winner's transaction had already committed — meaning that run proved
    correct WHERE-clause evaluation against committed state, not that the
    loser's statement actually blocked on a live row lock. The spec asks
    explicitly not to paper over that with a test that "passes trivially."

    This test forces the real thing: driver A's transaction issues its
    UPDATE and is deliberately held open (not committed) for `hold_seconds`.
    Driver B's UPDATE against the same row is fired while A's transaction is
    still open. If the atomic-UPDATE mechanism works as claimed, B's
    statement must physically block until A commits and releases the row
    lock — provably so, by timing B's call and asserting it took at least
    close to `hold_seconds`, not a few milliseconds.
    """
    phone_customer = "+919000006101"
    phone_a = "+919000006102"
    phone_b = "+919000006103"
    await _cleanup(phone_customer, phone_a, phone_b)

    async with SessionLocal() as setup_db:
        customer = User(phone=phone_customer)
        setup_db.add(customer)
        await setup_db.commit()
        await setup_db.refresh(customer)

        booking = await create_booking(
            setup_db,
            BookingCreate(
                pickup=_PICKUP,
                drop=_DROP,
                vehicle_type_code="bike",
                goods_description="Blocking test parcel",
                approx_weight_kg=5,
            ),
            customer,
        )
        public_code = booking.public_code

        driver_a = Driver(
            phone=phone_a,
            name="Driver A",
            vehicle_number="KA 05 AB 4444",
            vehicle_type_code="bike",
            is_online=True,
            is_verified=True,
        )
        driver_b = Driver(
            phone=phone_b,
            name="Driver B",
            vehicle_number="KA 05 AB 5555",
            vehicle_type_code="bike",
            is_online=True,
            is_verified=True,
        )
        setup_db.add_all([driver_a, driver_b])
        await setup_db.commit()
        await setup_db.refresh(driver_a)
        await setup_db.refresh(driver_b)

    hold_seconds = 0.5
    a_locked = asyncio.Event()

    async def _slow_winner(db) -> None:
        # The exact statement claim_booking issues, held open deliberately.
        result = await db.execute(
            update(Booking)
            .where(
                Booking.public_code == public_code,
                Booking.status == BookingStatus.pending,
                Booking.driver_id.is_(None),
            )
            .values(
                driver_id=driver_a.id,
                status=BookingStatus.driver_assigned,
                driver_assigned_at=func.now(),
            )
            .returning(Booking.id)
        )
        assert result.scalar_one_or_none() is not None
        a_locked.set()
        await asyncio.sleep(hold_seconds)
        await db.commit()

    async def _timed_loser(db) -> tuple[float, int | None]:
        await a_locked.wait()  # don't race the race — start only once A holds the lock
        start = time.monotonic()
        result = await db.execute(
            update(Booking)
            .where(
                Booking.public_code == public_code,
                Booking.status == BookingStatus.pending,
                Booking.driver_id.is_(None),
            )
            .values(
                driver_id=driver_b.id,
                status=BookingStatus.driver_assigned,
                driver_assigned_at=func.now(),
            )
            .returning(Booking.id)
        )
        elapsed = time.monotonic() - start
        matched = result.scalar_one_or_none()
        await db.commit()
        return elapsed, matched

    async with SessionLocal() as db_a, SessionLocal() as db_b:
        _, (elapsed, matched) = await asyncio.gather(
            _slow_winner(db_a), _timed_loser(db_b)
        )

    assert matched is None, "loser's UPDATE matched a row — it should have lost"
    assert elapsed >= hold_seconds * 0.8, (
        f"loser's UPDATE returned after {elapsed:.3f}s, expected to block for "
        f"~{hold_seconds}s — it did not genuinely wait on the row lock"
    )

    await _cleanup(phone_customer, phone_a, phone_b)


@pytest.mark.asyncio
async def test_same_driver_concurrent_accepts_on_two_bookings_exactly_one_wins():
    """Double-accept guard, tested for real. The same driver calls
    claim_booking on two *different* bookings at the same moment via
    asyncio.gather / two independent sessions. get_active_booking_for_driver
    (the pre-check in claim_booking) cannot close this race on its own —
    both calls can read "no active booking" before either commits, the same
    shape of race the whole spec exists to close. What actually decides the
    winner is the one_active_booking_per_driver partial unique index: the
    loser's UPDATE succeeds at the row level but fails at commit-time (well,
    statement-time — Postgres checks non-deferred unique indexes immediately)
    with a unique violation, which claim_booking catches and turns into
    DriverHasActiveBooking.
    """
    phone_customer = "+919000006201"
    phone_driver = "+919000006202"

    async def _cleanup_two_bookings() -> None:
        async with SessionLocal() as db:
            user_id = (
                await db.execute(select(User.id).where(User.phone == phone_customer))
            ).scalar_one_or_none()
            if user_id is not None:
                await db.execute(delete(Booking).where(Booking.customer_id == user_id))
                await db.execute(delete(User).where(User.id == user_id))
            await db.execute(delete(Driver).where(Driver.phone == phone_driver))
            await db.commit()

    await _cleanup_two_bookings()

    async with SessionLocal() as setup_db:
        customer = User(phone=phone_customer)
        setup_db.add(customer)
        await setup_db.commit()
        await setup_db.refresh(customer)

        booking_payload = dict(
            pickup=_PICKUP,
            drop=_DROP,
            vehicle_type_code="bike",
            approx_weight_kg=5,
        )
        booking_a = await create_booking(
            setup_db,
            BookingCreate(goods_description="Parcel A", **booking_payload),
            customer,
        )
        booking_b = await create_booking(
            setup_db,
            BookingCreate(goods_description="Parcel B", **booking_payload),
            customer,
        )
        code_a, code_b = booking_a.public_code, booking_b.public_code

        driver = Driver(
            phone=phone_driver,
            name="Double Accept Driver",
            vehicle_number="KA 05 AB 6666",
            vehicle_type_code="bike",
            is_online=True,
            is_verified=True,
        )
        setup_db.add(driver)
        await setup_db.commit()
        await setup_db.refresh(driver)

    async with SessionLocal() as db_a, SessionLocal() as db_b:
        results = await asyncio.gather(
            claim_booking(db_a, code_a, driver),
            claim_booking(db_b, code_b, driver),
            return_exceptions=True,
        )

    successes = [r for r in results if isinstance(r, Booking)]
    failures = [r for r in results if isinstance(r, BaseException)]

    assert len(successes) == 1, (
        f"expected exactly one winner, got {len(successes)}: {results}"
    )
    assert len(failures) == 1
    assert isinstance(failures[0], DriverHasActiveBooking), (
        f"expected DriverHasActiveBooking, got {failures[0]!r}"
    )

    async with SessionLocal() as verify_db:
        result = await verify_db.execute(
            select(Booking.public_code, Booking.status).where(
                Booking.driver_id == driver.id
            )
        )
        active_rows = [
            r
            for r in result.all()
            if r.status in (BookingStatus.driver_assigned, BookingStatus.picked_up)
        ]

    assert len(active_rows) == 1, (
        f"expected exactly one active booking for this driver, found {active_rows}"
    )
    assert active_rows[0].public_code == successes[0].public_code

    await _cleanup_two_bookings()


@pytest.mark.asyncio
async def test_second_accept_by_same_driver_blocks_on_partial_index_then_fails():
    """The test above can pass via the pre-check alone if driver B's
    get_active_booking_for_driver happens to run after A's transaction has
    already committed — checking the SQL trace of that exact test showed
    that's what happened: session B's failure was a clean SELECT-then-raise,
    no UPDATE ever attempted. That proves the pre-check works, not that the
    partial unique index does.

    This test forces the real mechanism: booking A's UPDATE is issued and
    held open (not committed) for hold_seconds. Booking B's UPDATE — same
    driver, different booking — is fired while A's transaction is still
    open. Postgres must block B on the one_active_booking_per_driver index
    (it can't know yet whether A's conflicting row will actually commit),
    then, once A commits, wake B and reject it with a uniqueness violation.
    Proven by timing B's call and asserting it actually raised
    IntegrityError, not merely that it returned quickly.
    """
    phone_customer = "+919000006301"
    phone_driver = "+919000006302"

    async def _cleanup_two_bookings() -> None:
        async with SessionLocal() as db:
            user_id = (
                await db.execute(select(User.id).where(User.phone == phone_customer))
            ).scalar_one_or_none()
            if user_id is not None:
                await db.execute(delete(Booking).where(Booking.customer_id == user_id))
                await db.execute(delete(User).where(User.id == user_id))
            await db.execute(delete(Driver).where(Driver.phone == phone_driver))
            await db.commit()

    await _cleanup_two_bookings()

    async with SessionLocal() as setup_db:
        customer = User(phone=phone_customer)
        setup_db.add(customer)
        await setup_db.commit()
        await setup_db.refresh(customer)

        booking_payload = dict(
            pickup=_PICKUP,
            drop=_DROP,
            vehicle_type_code="bike",
            approx_weight_kg=5,
        )
        booking_a = await create_booking(
            setup_db,
            BookingCreate(goods_description="Block test A", **booking_payload),
            customer,
        )
        booking_b = await create_booking(
            setup_db,
            BookingCreate(goods_description="Block test B", **booking_payload),
            customer,
        )
        code_a, code_b = booking_a.public_code, booking_b.public_code

        driver = Driver(
            phone=phone_driver,
            name="Block Test Driver",
            vehicle_number="KA 05 AB 7777",
            vehicle_type_code="bike",
            is_online=True,
            is_verified=True,
        )
        setup_db.add(driver)
        await setup_db.commit()
        await setup_db.refresh(driver)

    hold_seconds = 0.5
    a_locked = asyncio.Event()

    def _claim_update(public_code: str):
        return (
            update(Booking)
            .where(
                Booking.public_code == public_code,
                Booking.status == BookingStatus.pending,
                Booking.driver_id.is_(None),
            )
            .values(
                driver_id=driver.id,
                status=BookingStatus.driver_assigned,
                driver_assigned_at=func.now(),
            )
            .returning(Booking.id)
        )

    async def _slow_winner(db) -> None:
        result = await db.execute(_claim_update(code_a))
        assert result.scalar_one_or_none() is not None
        a_locked.set()
        await asyncio.sleep(hold_seconds)
        await db.commit()

    async def _timed_loser(db) -> tuple[float, Exception | None]:
        await a_locked.wait()
        start = time.monotonic()
        error: Exception | None = None
        try:
            await db.execute(_claim_update(code_b))
        except IntegrityError as e:
            error = e
        elapsed = time.monotonic() - start
        await db.rollback()
        return elapsed, error

    async with SessionLocal() as db_a, SessionLocal() as db_b:
        _, (elapsed, error) = await asyncio.gather(
            _slow_winner(db_a), _timed_loser(db_b)
        )

    assert error is not None, (
        "booking B's UPDATE should have failed with a uniqueness violation "
        "on one_active_booking_per_driver — it did not fail at all"
    )
    assert elapsed >= hold_seconds * 0.8, (
        f"booking B's UPDATE returned after {elapsed:.3f}s, expected to "
        f"block for ~{hold_seconds}s — it did not genuinely wait on the "
        "partial unique index"
    )

    await _cleanup_two_bookings()
