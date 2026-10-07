from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import delete

from app.database import SessionLocal
from app.main import app
from app.driver_auth import (
    DRIVER_NOT_REGISTERED,
    DRIVER_NOT_VERIFIED,
    get_authenticated_driver,
    get_current_driver,
)
from app.models.driver import Driver, VerificationStatus
from app.models.user import User


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


async def _resolve_current_driver(db, token: str = "whatever") -> Driver:
    """Walk the real dependency chain by hand.

    Spec 017 split the old single dependency in two: get_authenticated_driver
    resolves a token to a row, get_current_driver decides whether that row may
    work. FastAPI composes them; these tests have to do it explicitly, and
    doing it here rather than in each test keeps the composition in one place
    if it ever changes again.
    """
    driver = await get_authenticated_driver(creds=_creds(token), db=db)
    return await get_current_driver(driver=driver)


async def _cleanup(db, phone: str) -> None:
    await db.execute(delete(Driver).where(Driver.phone == phone))
    await db.execute(delete(User).where(User.phone == phone))
    await db.commit()


@pytest.mark.asyncio
async def test_valid_token_with_no_driver_row_raises_403():
    phone = "+919000005001"
    uid = "test-driver-uid-unregistered"

    async with SessionLocal() as db:
        await _cleanup(db, phone)

        decoded = {"uid": uid, "phone_number": phone}
        with patch("app.auth.firebase_auth.verify_id_token", return_value=decoded):
            with pytest.raises(HTTPException) as exc_info:
                await _resolve_current_driver(db)

        assert exc_info.value.status_code == 403
        # Assert on the CODE, not the prose. The app routes on this.
        assert exc_info.value.code == DRIVER_NOT_REGISTERED
        # And detail stays a plain STRING. See app/errors.py: an object here
        # breaks every already-sideloaded APK, which cannot be force-updated.
        assert isinstance(exc_info.value.detail, str)


@pytest.mark.asyncio
async def test_unverified_driver_raises_403():
    phone = "+919000005002"
    uid = "test-driver-uid-unverified"

    async with SessionLocal() as db:
        await _cleanup(db, phone)
        driver = Driver(
            firebase_uid=uid,
            phone=phone,
            name="Test Driver",
            vehicle_number="KA 05 AB 0001",
            vehicle_type_code="bike",
            is_verified=False,
        )
        db.add(driver)
        await db.commit()

        decoded = {"uid": uid, "phone_number": phone}
        with patch("app.auth.firebase_auth.verify_id_token", return_value=decoded):
            with pytest.raises(HTTPException) as exc_info:
                await _resolve_current_driver(db)

        assert exc_info.value.status_code == 403
        assert exc_info.value.code == DRIVER_NOT_VERIFIED
        assert isinstance(exc_info.value.detail, str)

        await _cleanup(db, phone)


@pytest.mark.asyncio
async def test_valid_verified_driver_is_returned():
    phone = "+919000005003"
    uid = "test-driver-uid-verified"

    async with SessionLocal() as db:
        await _cleanup(db, phone)
        driver = Driver(
            firebase_uid=uid,
            phone=phone,
            name="Test Driver",
            vehicle_number="KA 05 AB 0002",
            vehicle_type_code="bike",
            is_verified=True,
            # Must agree with is_verified — spec 017 derives one from the
            # other, so a fixture setting only the bool is inconsistent with
            # anything the app could actually produce.
            verification_status=VerificationStatus.approved,
        )
        db.add(driver)
        await db.commit()
        await db.refresh(driver)

        decoded = {"uid": uid, "phone_number": phone}
        with patch("app.auth.firebase_auth.verify_id_token", return_value=decoded):
            result = await _resolve_current_driver(db)

        assert result.id == driver.id

        await _cleanup(db, phone)


@pytest.mark.asyncio
async def test_same_uid_can_be_both_customer_and_driver():
    """Two rows, two principals, same Firebase uid — intentionally allowed."""
    phone = "+919000005004"
    uid = "test-uid-dual-role"

    async with SessionLocal() as db:
        await _cleanup(db, phone)

        user = User(phone=phone, firebase_uid=uid)
        driver = Driver(
            firebase_uid=uid,
            phone=phone,
            name="Dual Role",
            vehicle_number="KA 05 AB 0003",
            vehicle_type_code="bike",
            is_verified=True,
            verification_status=VerificationStatus.approved,
        )
        db.add_all([user, driver])
        await db.commit()
        await db.refresh(driver)

        decoded = {"uid": uid, "phone_number": phone}
        with patch("app.auth.firebase_auth.verify_id_token", return_value=decoded):
            result = await _resolve_current_driver(db)

        assert result.id == driver.id
        assert result.phone == phone

        await _cleanup(db, phone)


@pytest.mark.asyncio
async def test_not_registered_403_wire_shape_is_backward_compatible():
    """The ON-THE-WIRE body, not the exception object.

    This exists because of a real bug. Spec 017 first made `detail` an OBJECT
    carrying the code, every test passed, and a driver with no profile landed
    on the app's dead-end error screen against production — which was running
    an older build that sent a plain string. The app had been changed to
    require a field the deployed server did not send.

    The shape that survives version skew in BOTH directions is a string
    `detail` (what every already-shipped APK reads) plus a SIBLING `code` (what
    a newer app branches on). An old app ignores the code; a new app tolerates
    its absence. Assert both halves, because either one alone is the bug.
    """
    phone = "+919000005009"
    uid = "test-driver-uid-wire-shape"

    async with SessionLocal() as db:
        await _cleanup(db, phone)

    decoded = {"uid": uid, "phone_number": phone}
    with patch("app.auth.firebase_auth.verify_id_token", return_value=decoded):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/drivers/me",
                headers={"Authorization": "Bearer pretend-token"},
            )

    assert response.status_code == 403
    body = response.json()

    # Half one: old apps substring-match this. It must stay a string.
    assert isinstance(body["detail"], str), (
        "detail must remain a plain string — sideloaded APKs cannot be "
        "force-updated, and an object here breaks every one already installed"
    )
    assert body["detail"] == "Not registered as a driver"

    # Half two: new apps route on this.
    assert body["code"] == DRIVER_NOT_REGISTERED
