from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import _bearer, verify_token
from app.database import get_db
from app.models.driver import Driver

# Machine-readable reasons for the two driver-auth 403s.
#
# These are the ONLY endpoints whose `detail` is an object rather than a
# string. That is a deliberate exception, not a second error standard: the
# driver app ROUTES on the difference between these two, and it previously did
# so by substring-matching the prose below — so a copy-edit to a user-facing
# sentence would have silently sent every registered driver back to the
# registration form. Everywhere else `detail` stays a plain string, and the
# client tolerates both shapes.
DRIVER_NOT_REGISTERED = "driver_not_registered"
DRIVER_NOT_VERIFIED = "driver_not_verified"


def _coded(code: str, message: str) -> dict[str, str]:
    """A 403 body the app can branch on without reading English."""
    return {"code": code, "message": message}


async def get_authenticated_driver(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> Driver:
    """Identity only: a valid token and a matching Driver row. NO verification
    check.

    This exists because spec 017 would otherwise be circular — a driver has to
    read their own verification_status to know they must upload documents, and
    has to upload documents to become verified. Gating those two paths on
    is_verified means a pending driver can never reach the screen that would
    let them stop being pending.

    ONLY three routes may use this: GET /drivers/me, and the two document
    endpoints. Everything a driver does that touches a booking or the job
    board uses get_current_driver below, so the verification gate is exactly
    where it has always been.

    Unlike get_current_user, this does NOT create a row on first sight —
    drivers must register explicitly (POST /drivers/register), because a
    driver record needs a vehicle and a plate number that Firebase knows
    nothing about.

    A phone number can legitimately be both a customer and a driver: two
    rows, two principals, same Firebase uid. That's fine and intentional.
    """
    decoded = await verify_token(creds)
    uid = decoded["uid"]

    result = await db.execute(select(Driver).where(Driver.firebase_uid == uid))
    driver = result.scalar_one_or_none()

    if driver is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_coded(DRIVER_NOT_REGISTERED, "Not registered as a driver"),
        )

    return driver


async def get_current_driver(
    driver: Driver = Depends(get_authenticated_driver),
) -> Driver:
    """An authenticated AND VERIFIED driver. The gate for everything
    operational.

    Layered on get_authenticated_driver rather than duplicating the lookup, so
    there is one place that resolves a token to a row and one place that
    decides whether that row may work.

    is_verified is derived from verification_status == approved as of spec 017;
    before that it was hardcoded True at registration. This check did not
    change shape, which was the point of keeping the column.
    """
    if not driver.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_coded(
                DRIVER_NOT_VERIFIED, "Driver account pending verification"
            ),
        )

    return driver
