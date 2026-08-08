import firebase_admin
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.database import get_db
from app.models.user import User

_bearer = HTTPBearer(auto_error=True)


def init_firebase() -> None:
    """Idempotent. Called once at app startup."""
    if not firebase_admin._apps:
        cred = credentials.Certificate(get_settings().firebase_credentials_path)
        firebase_admin.initialize_app(cred)


async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Verifies the Firebase ID token and returns the matching User row,
    creating it on first sign-in.

    This is the only trustworthy source of caller identity. Nothing from the
    request body is ever used to decide who the caller is.
    """
    try:
        # verify_id_token is blocking (network call to fetch Google's public
        # keys, though they are cached). Off the event loop it goes.
        decoded = await run_in_threadpool(
            firebase_auth.verify_id_token, creds.credentials
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    uid = decoded.get("uid")
    phone = decoded.get("phone_number")
    if not uid or not phone:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing uid or phone_number",
        )

    result = await db.execute(select(User).where(User.firebase_uid == uid))
    user = result.scalar_one_or_none()

    if user is None:
        # A user row may already exist from pre-auth testing — link it rather
        # than creating a duplicate, since phone is unique.
        result = await db.execute(select(User).where(User.phone == phone))
        user = result.scalar_one_or_none()
        if user is not None:
            user.firebase_uid = uid
        else:
            user = User(phone=phone, firebase_uid=uid)
            db.add(user)
        await db.commit()
        await db.refresh(user)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled"
        )

    return user
