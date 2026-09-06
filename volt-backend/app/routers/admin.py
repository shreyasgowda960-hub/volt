"""Document review, for the owner.

THE AUTH HERE IS INTERIM AND WEAK, AND THAT IS A DELIBERATE, TEMPORARY CHOICE.
A single shared secret in ADMIN_REVIEW_TOKEN, sent as X-Admin-Token:

  * No audit trail. Every approval is "whoever had the token". reviewed_by is
    free text supplied by the caller, which means it records a claim, not an
    identity.
  * No per-person revocation. With one reviewer that is not a distinction;
    with two it is the whole problem, because revoking for one revokes for
    both and needs a redeploy.
  * No expiry, and it sits in an environment variable on Render.

Accepted because the alternative today is an admin user table and a login
flow for a single person. Replaced by real admin auth the moment a second
person reviews documents, or when the React dashboard arrives — whichever
comes first. Recorded in docs/future-plans.md with that trigger.

There is NO ADMIN UI here and there must not be one in this spec. Review
happens through these endpoints; the dashboard is phase 5.
"""

import hmac
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.schemas.driver_document import (
    AdminDocumentResponse,
    AdminPendingDriverResponse,
    RejectRequest,
)
from app.services import driver_verification, storage
from app.services.driver_verification import DriverNotFound
from app.services.storage import StorageError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


async def require_admin_token(
    x_admin_token: str | None = Header(default=None),
) -> str:
    """Constant-time comparison against the configured secret.

    An unset token gives 503, NOT an open endpoint. That is the failure
    direction that matters: a misconfigured deploy must refuse everyone rather
    than admit everyone, and a 503 says "this is not set up" instead of
    silently exposing every driver's licence.
    """
    settings = get_settings()
    expected = settings.admin_review_token

    if not expected:
        logger.error("admin review attempted but ADMIN_REVIEW_TOKEN is unset")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document review is not configured",
        )

    # compare_digest rather than ==, so a wrong token cannot be recovered a
    # byte at a time from response timing. Cheap, and the alternative is
    # indefensible for a shared secret with no rate limit in front of it.
    if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        logger.warning("admin review rejected: bad or missing X-Admin-Token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authorised",
        )

    return x_admin_token


@router.get(
    "/drivers/pending",
    response_model=list[AdminPendingDriverResponse],
    dependencies=[Depends(require_admin_token)],
)
async def list_pending_drivers(
    db: AsyncSession = Depends(get_db),
) -> list[AdminPendingDriverResponse]:
    """Drivers awaiting review, with a short-lived signed URL per document.

    THIS IS THE ONLY ENDPOINT THAT ISSUES SIGNED URLS. Storage rules deny all
    client reads, so a URL from here is the only way to see an image — which
    is why the expiry is 15 minutes (storage.SIGNED_URL_TTL) rather than a day.
    """
    drivers = await driver_verification.pending_drivers(db)
    service = storage.default_storage_service()

    out: list[AdminPendingDriverResponse] = []
    for driver in drivers:
        documents = await driver_verification.list_documents(db, driver.id)
        rendered: list[AdminDocumentResponse] = []
        for document in documents:
            try:
                url = await service.signed_url(document.storage_path)
            except StorageError:
                # One unreadable object must not hide the whole queue. The
                # reviewer sees the row with an empty URL and can chase it,
                # which is more useful than a 503 for the entire list.
                logger.error(
                    "could not sign %s for review", document.storage_path
                )
                url = ""
            rendered.append(
                AdminDocumentResponse(
                    id=document.id,
                    document_type=document.document_type,
                    status=document.status,
                    document_number=document.document_number,
                    rejection_reason=document.rejection_reason,
                    uploaded_at=document.uploaded_at,
                    reviewed_at=document.reviewed_at,
                    signed_url=url,
                )
            )
        out.append(
            AdminPendingDriverResponse(
                id=driver.id,
                name=driver.name,
                phone=driver.phone,
                vehicle_number=driver.vehicle_number,
                vehicle_type_code=driver.vehicle_type_code,
                verification_status=driver.verification_status,
                documents=rendered,
            )
        )
    return out


@router.post(
    "/drivers/{driver_id}/approve",
    dependencies=[Depends(require_admin_token)],
)
async def approve_driver(
    driver_id: int,
    reviewed_by: str = "owner",
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """The only path to is_verified=True. Nothing auto-approves."""
    try:
        driver = await driver_verification.approve_driver(
            db, driver_id, reviewed_by
        )
    except DriverNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found"
        )
    return {
        "driver_id": driver.id,
        "verification_status": driver.verification_status.value,
        "is_verified": driver.is_verified,
    }


@router.post(
    "/drivers/{driver_id}/reject",
    dependencies=[Depends(require_admin_token)],
)
async def reject_driver(
    driver_id: int,
    payload: RejectRequest,
    reviewed_by: str = "owner",
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Reject named documents with a reason the DRIVER will read.

    The schema enforces a 10-character minimum on the reason, because
    "invalid" is a legal string and a useless one — see RejectRequest.
    """
    try:
        driver = await driver_verification.reject_driver(
            db,
            driver_id,
            payload.reason,
            payload.document_types,
            reviewed_by,
        )
    except DriverNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found"
        )
    return {
        "driver_id": driver.id,
        "verification_status": driver.verification_status.value,
        "is_verified": driver.is_verified,
        "rejected": [d.value for d in payload.document_types],
    }


@router.delete(
    "/drivers/{driver_id}/documents",
    dependencies=[Depends(require_admin_token)],
)
async def delete_driver_documents(
    driver_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """RETENTION. Deletes a driver's documents from Storage and the database.

    Callable, not scheduled — see driver_verification.delete_all_documents for
    why this exists at all rather than being left as a later cleanup. Under
    the DPDP Act personal data is kept for the purpose it was collected for
    and deleted when that purpose ends; indefinite storage is not a lawful
    default, and licences are the most sensitive data VOLT holds.

    Exposed under admin rather than as a driver self-service action because
    deleting documents also resets the driver to pending, which revokes their
    ability to work. That should be a deliberate act, not a mis-tap.
    """
    removed = await driver_verification.delete_all_documents(db, driver_id)
    return {"driver_id": driver_id, "documents_deleted": removed}
