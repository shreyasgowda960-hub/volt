from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import delete, select

from app.auth import get_current_user
from app.database import SessionLocal
from app.models.user import User


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


@pytest.mark.asyncio
async def test_invalid_token_raises_401():
    async with SessionLocal() as db:
        with patch(
            "app.auth.firebase_auth.verify_id_token",
            side_effect=ValueError("invalid token"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(creds=_creds("garbage"), db=db)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_valid_token_unknown_uid_creates_user():
    phone = "+919000000001"
    uid = "test-uid-new-user"

    async with SessionLocal() as db:
        await db.execute(delete(User).where(User.phone == phone))
        await db.commit()

        decoded = {"uid": uid, "phone_number": phone}
        with patch("app.auth.firebase_auth.verify_id_token", return_value=decoded):
            user = await get_current_user(creds=_creds("whatever"), db=db)

        assert user.phone == phone
        assert user.firebase_uid == uid

        await db.execute(delete(User).where(User.phone == phone))
        await db.commit()


@pytest.mark.asyncio
async def test_valid_token_existing_phone_links_uid_not_duplicate():
    phone = "+919000000002"
    uid = "test-uid-link-existing"

    async with SessionLocal() as db:
        await db.execute(delete(User).where(User.phone == phone))
        await db.commit()

        existing = User(phone=phone)
        db.add(existing)
        await db.commit()
        await db.refresh(existing)

        decoded = {"uid": uid, "phone_number": phone}
        with patch("app.auth.firebase_auth.verify_id_token", return_value=decoded):
            user = await get_current_user(creds=_creds("whatever"), db=db)

        assert user.id == existing.id
        assert user.firebase_uid == uid

        result = await db.execute(select(User).where(User.phone == phone))
        assert len(result.scalars().all()) == 1

        await db.execute(delete(User).where(User.phone == phone))
        await db.commit()
