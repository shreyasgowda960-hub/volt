from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import _bearer, verify_token
from app.database import get_db
from app.models.driver import Driver


async def get_current_driver(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> Driver:
    """Verifies the Firebase ID token and returns the matching Driver row.

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
            detail="Not registered as a driver",
        )

    if not driver.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Driver account pending verification",
        )

    return driver
