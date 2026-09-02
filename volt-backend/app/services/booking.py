from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.booking import Booking, BookingStatus, CancelledBy
from app.models.driver import Driver
from app.models.user import User
from app.schemas.booking import BookingCreate
from app.services.booking_lifecycle import (
    BookingAlreadyClaimed,
    BookingExpired,
    BookingNotFound,
    DriverHasActiveBooking,
    DriverOffline,
    IllegalTransition,
    VehicleTypeMismatch,
    timestamp_column_for,
)
from app.services.fare import VehicleCapacityExceeded, _fare_paise, load_vehicle_type
from app.utils.codes import generate_public_code
from app.utils.distance import eta_minutes, road_distance_m

EXPIRY_MINUTES = 5


async def _unique_public_code(db: AsyncSession) -> str:
    for _ in range(5):
        code = generate_public_code()
        existing = await db.execute(
            select(Booking.id).where(Booking.public_code == code)
        )
        if existing.scalar_one_or_none() is None:
            return code
    raise RuntimeError("could not generate a unique booking code")


async def create_booking(
    db: AsyncSession, payload: BookingCreate, user: User
) -> Booking:
    vehicle = await load_vehicle_type(db, payload.vehicle_type_code)
    if payload.approx_weight_kg > vehicle.capacity_kg:
        raise VehicleCapacityExceeded(payload.approx_weight_kg, vehicle)

    distance_m = road_distance_m(
        payload.pickup.lat,
        payload.pickup.lng,
        payload.drop.lat,
        payload.drop.lng,
    )

    booking = Booking(
        public_code=await _unique_public_code(db),
        customer_id=user.id,
        vehicle_type_code=vehicle.code,
        status=BookingStatus.pending,
        pickup_address=payload.pickup.address,
        pickup_lat=payload.pickup.lat,
        pickup_lng=payload.pickup.lng,
        drop_address=payload.drop.address,
        drop_lat=payload.drop.lat,
        drop_lng=payload.drop.lng,
        goods_description=payload.goods_description,
        approx_weight_kg=payload.approx_weight_kg,
        quoted_fare_paise=_fare_paise(vehicle, distance_m),
        quoted_distance_m=distance_m,
        quoted_eta_minutes=eta_minutes(distance_m),
        # Rate snapshot: changing vehicle_types next month must never rewrite
        # what this booking was quoted.
        quoted_base_fare_paise=vehicle.base_fare_paise,
        quoted_included_km=vehicle.included_km,
        quoted_per_km_paise=vehicle.per_km_paise,
        quoted_min_fare_paise=vehicle.min_fare_paise,
        payment_method=payload.payment_method,
    )
    db.add(booking)
    await db.commit()
    await db.refresh(booking)
    return booking


async def get_booking_by_code(
    db: AsyncSession, public_code: str
) -> Booking | None:
    result = await db.execute(
        select(Booking).where(Booking.public_code == public_code)
    )
    return result.scalar_one_or_none()


async def get_booking_with_driver(
    db: AsyncSession, public_code: str
) -> Booking | None:
    """Same as get_booking_by_code, but with the driver eagerly loaded.

    Deliberately a separate function rather than an option on
    get_booking_by_code: that one is also the first step of claim_booking,
    mark_picked_up, mark_delivered and cancel_booking, none of which touch
    booking.driver. Loading it there would add a query to every driver
    action to serve a field only the customer endpoints return.
    """
    result = await db.execute(
        select(Booking)
        .options(selectinload(Booking.driver))
        .where(Booking.public_code == public_code)
    )
    return result.scalar_one_or_none()


async def list_bookings_for_user(
    db: AsyncSession, customer_id: int, limit: int
) -> list[Booking]:
    # selectinload, not a join or lazy access: Booking.driver is lazy="raise",
    # so serialising this list without it raises. It also keeps the cost at
    # one extra query for the whole page — a lazy relationship here would be
    # the textbook N+1, one SELECT per booking returned.
    result = await db.execute(
        select(Booking)
        .options(selectinload(Booking.driver))
        .where(Booking.customer_id == customer_id)
        .order_by(Booking.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_active_booking_for_driver(
    db: AsyncSession, driver_id: int
) -> Booking | None:
    """A booking this driver is currently on the hook for. Used to block
    going offline mid-job (see mark_offline in app/routers/drivers.py)."""
    result = await db.execute(
        select(Booking)
        .where(
            Booking.driver_id == driver_id,
            Booking.status.in_(
                [BookingStatus.driver_assigned, BookingStatus.picked_up]
            ),
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def expire_stale_bookings(db: AsyncSession) -> int:
    """Marks pending bookings older than EXPIRY_MINUTES as expired.

    Called at the start of endpoints that read booking state, rather than run
    on a schedule. Idempotent and cheap — one UPDATE against an indexed
    column, using the database's clock (func.now()) so app servers with
    slightly different clocks — or several of them — can't disagree about
    what counts as stale.

    LIMITATION: if nobody calls the API, bookings stay pending past 5 minutes
    until someone does. Acceptable now; replace with a scheduled job when
    there is real traffic.
    """
    result = await db.execute(
        update(Booking)
        .where(
            Booking.status == BookingStatus.pending,
            Booking.created_at < func.now() - timedelta(minutes=EXPIRY_MINUTES),
        )
        .values(
            status=BookingStatus.expired,
            **{timestamp_column_for(BookingStatus.expired): func.now()},
        )
    )
    await db.commit()
    return result.rowcount


async def claim_booking(db: AsyncSession, public_code: str, driver: Driver) -> Booking:
    """Assigns a pending booking to a driver, atomically.

    Two drivers tapping Accept simultaneously both read status='pending'
    before either writes. A read-then-write would assign both. Instead the
    WHERE clause below carries the precondition, so Postgres decides the
    winner: exactly one UPDATE matches a row, the rest match zero.

    This "zero rows on loss" behaviour depends on READ COMMITTED, Postgres's
    default isolation level: the losing UPDATE blocks on the winner's row
    lock, then — once it can proceed — re-evaluates its WHERE clause against
    the now-committed row and finds it no longer matches, so it simply
    touches nothing. Under REPEATABLE READ or SERIALIZABLE, the loser would
    instead raise a serialization-failure error and need explicit retry
    handling. Do not raise the isolation level here without adding that.

    Do NOT rewrite this as "select, check, update" — that reintroduces
    exactly the race this function exists to close. The vehicle-type and
    online checks below are a SELECT first because they're safe to check
    early: neither can change between the check and the UPDATE (vehicle type
    is immutable on a booking, and this driver is the only one who can take
    themselves offline). Only the pending/unclaimed precondition — the one
    thing another driver's request can race against — lives in the UPDATE's
    WHERE clause.

    The "does this driver already have an active booking" check below has
    that exact same shape of race: two simultaneous accepts by the same
    driver, on two different bookings, could both pass a SELECT-based check
    before either commits. So it isn't the real guard — it's a friendly
    message for the common case. The real guard is the
    one_active_booking_per_driver partial unique index (bookings.driver_id,
    WHERE status IN driver_assigned/picked_up): if both UPDATEs somehow get
    past the pre-check, the database itself rejects the second one with a
    unique-violation IntegrityError, caught below and turned into the same
    409 the friendly path would have given.
    """
    if not driver.is_online:
        raise DriverOffline()

    booking = await get_booking_by_code(db, public_code)
    if booking is None:
        raise BookingNotFound(public_code)
    if booking.vehicle_type_code != driver.vehicle_type_code:
        raise VehicleTypeMismatch(driver.vehicle_type_code, booking.vehicle_type_code)

    active = await get_active_booking_for_driver(db, driver.id)
    if active is not None:
        raise DriverHasActiveBooking(active.public_code)

    try:
        result = await db.execute(
            update(Booking)
            .where(
                Booking.public_code == public_code,
                Booking.status == BookingStatus.pending,
                Booking.driver_id.is_(None),
            )
            .values(
                driver_id=driver.id,
                status=BookingStatus.driver_assigned,
                **{timestamp_column_for(BookingStatus.driver_assigned): func.now()},
            )
            .returning(Booking.id)
        )
    except IntegrityError:
        # Lost the race the pre-check above can't close: another accept by
        # this same driver, on a different booking, committed in between our
        # pre-check and this UPDATE. one_active_booking_per_driver rejected
        # us. Session is now aborted — roll back before touching it again.
        await db.rollback()
        active_now = await get_active_booking_for_driver(db, driver.id)
        raise DriverHasActiveBooking(
            active_now.public_code if active_now is not None else public_code
        )
    claimed_id = result.scalar_one_or_none()

    if claimed_id is None:
        # Zero rows matched. Either someone else's UPDATE got there first, or
        # expire_stale_bookings beat both of us to it. Those need different
        # messages: telling a driver "someone else took it" when the booking
        # actually just expired is actively misleading. Still inside this
        # transaction, so under READ COMMITTED this re-read sees whichever
        # write just committed and released the row lock we were blocked on.
        current = await get_booking_by_code(db, public_code)
        # Capture before rollback: rollback() expires every object in the
        # session, and touching an expired attribute afterward triggers an
        # implicit reload that the async ORM can't perform outside an
        # explicit await — it raises MissingGreenlet instead of quietly
        # doing the wrong thing, which is at least loud about it.
        current_status = current.status if current is not None else None
        await db.rollback()
        if current_status == BookingStatus.expired:
            raise BookingExpired(public_code)
        raise BookingAlreadyClaimed(public_code)

    await db.commit()
    await db.refresh(booking)
    return booking


async def mark_picked_up(db: AsyncSession, public_code: str, driver: Driver) -> Booking:
    booking = await get_booking_by_code(db, public_code)
    # Not found and "found but not yours" answer the same way on purpose —
    # see the 404-not-403 note on GET /bookings/{code}. A 403 here would
    # confirm the booking exists, making codes worth guessing.
    if booking is None or booking.driver_id != driver.id:
        raise BookingNotFound(public_code)

    result = await db.execute(
        update(Booking)
        .where(
            Booking.public_code == public_code,
            Booking.status == BookingStatus.driver_assigned,
        )
        .values(
            status=BookingStatus.picked_up,
            **{timestamp_column_for(BookingStatus.picked_up): func.now()},
        )
        .returning(Booking.id)
    )
    if result.scalar_one_or_none() is None:
        # Re-read rather than trust the SELECT at the top of this function.
        # Under READ COMMITTED that snapshot can be stale by now, and naming
        # the wrong current status sends whoever reads the log hunting the
        # wrong bug. Same reasoning as claim_booking's zero-rows branch.
        current = await get_booking_by_code(db, public_code)
        # Captured before rollback: rollback expires every ORM object, and
        # touching one afterwards raises MissingGreenlet on an async session.
        from_status = current.status if current is not None else booking.status
        await db.rollback()
        raise IllegalTransition(from_status, BookingStatus.picked_up)

    await db.commit()
    await db.refresh(booking)
    return booking


async def mark_delivered(db: AsyncSession, public_code: str, driver: Driver) -> Booking:
    booking = await get_booking_by_code(db, public_code)
    if booking is None or booking.driver_id != driver.id:
        raise BookingNotFound(public_code)

    result = await db.execute(
        update(Booking)
        .where(
            Booking.public_code == public_code,
            Booking.status == BookingStatus.picked_up,
        )
        .values(
            status=BookingStatus.delivered,
            **{timestamp_column_for(BookingStatus.delivered): func.now()},
        )
        .returning(Booking.id)
    )
    if result.scalar_one_or_none() is None:
        # Re-read rather than trust the SELECT at the top of this function.
        # Under READ COMMITTED that snapshot can be stale by now, and naming
        # the wrong current status sends whoever reads the log hunting the
        # wrong bug. Same reasoning as claim_booking's zero-rows branch.
        current = await get_booking_by_code(db, public_code)
        # Captured before rollback: rollback expires every ORM object, and
        # touching one afterwards raises MissingGreenlet on an async session.
        from_status = current.status if current is not None else booking.status
        await db.rollback()
        raise IllegalTransition(from_status, BookingStatus.delivered)

    await db.commit()
    await db.refresh(booking)
    return booking


async def cancel_booking(
    db: AsyncSession,
    public_code: str,
    user: User,
    cancellation_reason: str | None = None,
) -> Booking:
    """Free any time before pickup — phase 1 decision, no fee logic. Once
    picked_up, cancellation is a support problem (the state machine already
    enforces this: picked_up has no cancelled edge), not a self-service one.
    """
    booking = await get_booking_by_code(db, public_code)
    if booking is None or booking.customer_id != user.id:
        raise BookingNotFound(public_code)

    result = await db.execute(
        update(Booking)
        .where(
            Booking.public_code == public_code,
            Booking.status.in_([BookingStatus.pending, BookingStatus.driver_assigned]),
        )
        .values(
            status=BookingStatus.cancelled,
            cancelled_by=CancelledBy.customer,
            cancellation_reason=cancellation_reason,
            **{timestamp_column_for(BookingStatus.cancelled): func.now()},
        )
        .returning(Booking.id)
    )
    if result.scalar_one_or_none() is None:
        # Re-read rather than trust the SELECT at the top of this function.
        # Under READ COMMITTED that snapshot can be stale by now, and naming
        # the wrong current status sends whoever reads the log hunting the
        # wrong bug. Same reasoning as claim_booking's zero-rows branch.
        current = await get_booking_by_code(db, public_code)
        # Captured before rollback: rollback expires every ORM object, and
        # touching one afterwards raises MissingGreenlet on an async session.
        from_status = current.status if current is not None else booking.status
        await db.rollback()
        raise IllegalTransition(from_status, BookingStatus.cancelled)

    await db.commit()
    await db.refresh(booking)
    return booking
