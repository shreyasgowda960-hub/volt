import logging

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import _bearer, verify_token
from app.database import get_db
from app.driver_auth import get_authenticated_driver, get_current_driver
from app.models.booking import Booking, BookingStatus
from app.models.driver import Driver
from app.models.driver_document import DocumentType
from app.schemas.booking import BookingResponse
from app.schemas.driver import AvailabilityUpdate, DriverRegister, DriverResponse
from app.schemas.driver_document import (
    DriverDocumentResponse,
    DriverDocumentsResponse,
)
from app.services import booking as booking_service
from app.services import driver_verification
from app.services.driver_verification import (
    DocumentAlreadyPresent,
    DocumentTooLarge,
    UnsupportedDocumentFormat,
)
from app.services.fare import VehicleTypeNotFound, load_vehicle_type
from app.services.storage import MAX_UPLOAD_BYTES, StorageError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/drivers", tags=["drivers"])


@router.post(
    "/register",
    response_model=DriverResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_driver(
    payload: DriverRegister,
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> DriverResponse:
    # get_current_driver can't be used here — the driver row doesn't exist
    # yet, and that dependency 403s when it doesn't find one.
    decoded = await verify_token(creds)
    uid = decoded["uid"]
    phone = decoded["phone_number"]

    existing = await db.execute(select(Driver.id).where(Driver.firebase_uid == uid))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Driver already registered for this account",
        )

    try:
        await load_vehicle_type(db, payload.vehicle_type_code)
    except VehicleTypeNotFound:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown vehicle type: {payload.vehicle_type_code}",
        )

    driver = Driver(
        firebase_uid=uid,
        phone=phone,
        name=payload.name,
        vehicle_number=payload.vehicle_number,
        vehicle_type_code=payload.vehicle_type_code,
        # NOT verified. Spec 008 auto-verified here and spec 017 removed it:
        # a new driver starts is_verified=False / verification_status=pending
        # (both column defaults) and becomes verified only when a human
        # approves their documents. Do not set either field here again.
    )
    db.add(driver)
    await db.commit()
    await db.refresh(driver)
    return DriverResponse.model_validate(driver)


# get_authenticated_driver, NOT get_current_driver. An unverified driver must
# be able to read their own profile — verification_status is what the driver
# app routes on, and gating it on is_verified makes spec 017 circular: the
# driver cannot learn they need to upload documents without being verified,
# and cannot be verified without uploading documents.
@router.get("/me", response_model=DriverResponse)
async def get_me(
    driver: Driver = Depends(get_authenticated_driver),
) -> DriverResponse:
    return DriverResponse.model_validate(driver)


@router.post(
    "/me/documents",
    response_model=DriverDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    document_type: DocumentType = Form(...),
    file: UploadFile = File(...),
    document_number: str | None = Form(default=None),
    driver: Driver = Depends(get_authenticated_driver),
    db: AsyncSession = Depends(get_db),
) -> DriverDocumentResponse:
    """Upload one document. Unverified by definition — see get_me above."""
    # Read once. The declared content type on the part is NOT consulted: it is
    # caller-supplied, and driver_verification sniffs the actual bytes.
    data = await file.read()

    try:
        document = await driver_verification.submit_document(
            db,
            driver,
            document_type,
            data,
            document_number=(document_number or None),
        )
    except DocumentTooLarge as e:
        logger.info("upload refused for driver %s: %d bytes", driver.id, e.size)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"That file is too large. The limit is "
                f"{MAX_UPLOAD_BYTES // (1024 * 1024)}MB."
            ),
        )
    except UnsupportedDocumentFormat:
        logger.info("upload refused for driver %s: unrecognised bytes", driver.id)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Upload a JPG, PNG or PDF.",
        )
    except DocumentAlreadyPresent as e:
        # 409, not 422: nothing is wrong with the request, it is the state that
        # refuses it. Same distinction as the booking lifecycle's 409s.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Your {e.document_type.value.replace('_', ' ')} is already "
                "submitted. Wait for the review, or resubmit if it is rejected."
            ),
        )
    except StorageError:
        # 503, not 500: nothing is wrong with our code or the request, the
        # upstream store refused. Deliberately NOT degraded the way routing is
        # — a document upload that silently fails leaves a driver believing
        # they submitted something.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not upload right now. Please try again.",
        )

    return DriverDocumentResponse.model_validate(document)


@router.get("/me/documents", response_model=DriverDocumentsResponse)
async def list_my_documents(
    driver: Driver = Depends(get_authenticated_driver),
    db: AsyncSession = Depends(get_db),
) -> DriverDocumentsResponse:
    """The driver's own documents, with status and any rejection reason.

    NO SIGNED URLS. A driver does not need to re-read their own upload — they
    took the photo — and issuing URLs here would widen the surface for no
    gain. Signed URLs exist on the admin response only.
    """
    documents = await driver_verification.list_documents(db, driver.id)
    return DriverDocumentsResponse(
        verification_status=driver.verification_status,
        documents=[
            DriverDocumentResponse.model_validate(d) for d in documents
        ],
    )


@router.patch("/me/availability", response_model=DriverResponse)
async def update_availability(
    payload: AvailabilityUpdate,
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
) -> DriverResponse:
    if not payload.is_online and driver.is_online:
        active = await booking_service.get_active_booking_for_driver(db, driver.id)
        if active is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot go offline while booking {active.public_code} "
                    "is in progress"
                ),
            )

    driver.is_online = payload.is_online
    await db.commit()
    await db.refresh(driver)
    return DriverResponse.model_validate(driver)


@router.get("/jobs", response_model=list[BookingResponse])
async def list_jobs(
    limit: int = Query(default=20, ge=1, le=50),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
) -> list[BookingResponse]:
    if not driver.is_online:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Go online to see jobs",
        )

    await booking_service.expire_stale_bookings(db)

    result = await db.execute(
        select(Booking)
        .where(
            Booking.status == BookingStatus.pending,
            Booking.driver_id.is_(None),
            Booking.vehicle_type_code == driver.vehicle_type_code,
        )
        .order_by(Booking.created_at.desc())
        .limit(limit)
    )
    return [BookingResponse.model_validate(b) for b in result.scalars().all()]


@router.get("/bookings", response_model=list[BookingResponse])
async def list_my_bookings(
    limit: int = Query(default=20, ge=1, le=100),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
) -> list[BookingResponse]:
    result = await db.execute(
        select(Booking)
        .where(Booking.driver_id == driver.id)
        .order_by(Booking.created_at.desc())
        .limit(limit)
    )
    return [BookingResponse.model_validate(b) for b in result.scalars().all()]
