from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import delete

from app.database import SessionLocal
from app.driver_auth import get_authenticated_driver, get_current_driver
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
        assert "Not registered" in exc_info.value.detail


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
        assert "pending verification" in exc_info.value.detail

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
