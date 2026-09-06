"""Driver document submission and review (spec 017).

The state machine here loops, unlike the booking lifecycle:

    pending --upload both--> submitted --approve--> approved
                                  |
                                  +---reject---> rejected --resubmit--> submitted

`is_verified` is DERIVED from verification_status and written only by
approve/reject in this module. Nothing else may set it — before this spec it
was hardcoded True at registration, which is the thing the spec exists to
remove.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver import Driver, VerificationStatus
from app.models.driver_document import (
    DocumentStatus,
    DocumentType,
    DriverDocument,
)
from app.services import storage

logger = logging.getLogger(__name__)

# Magic numbers, checked against the actual bytes. The declared Content-Type
# on a multipart part is caller-supplied and means nothing: a .exe can be
# announced as image/jpeg. These three are the only accepted shapes.
_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"%PDF-", "application/pdf"),
)


class DocumentTooLarge(Exception):
    def __init__(self, size: int) -> None:
        self.size = size
        super().__init__(f"{size} bytes exceeds the limit")


class UnsupportedDocumentFormat(Exception):
    """The bytes are not a JPEG, PNG or PDF, whatever the request claimed."""


class DocumentAlreadyPresent(Exception):
    def __init__(self, document_type: DocumentType) -> None:
        self.document_type = document_type
        super().__init__(f"a live {document_type.value} already exists")


class DriverNotFound(Exception):
    pass


def sniff_content_type(data: bytes) -> str:
    """The real content type, from the leading bytes.

    Raises rather than returning None: there is no sensible default, and a
    caller that forgot to check the return value would otherwise store an
    arbitrary file.
    """
    for signature, content_type in _SIGNATURES:
        if data.startswith(signature):
            return content_type
    raise UnsupportedDocumentFormat()


def validate_upload(data: bytes) -> str:
    """Size then format. Returns the sniffed content type."""
    if len(data) > storage.MAX_UPLOAD_BYTES:
        raise DocumentTooLarge(len(data))
    if not data:
        raise UnsupportedDocumentFormat()
    return sniff_content_type(data)


async def _live_documents(
    db: AsyncSession, driver_id: int
) -> list[DriverDocument]:
    """Everything not rejected. Rejected rows stay on the record forever but
    do not count towards completeness."""
    result = await db.execute(
        select(DriverDocument).where(
            DriverDocument.driver_id == driver_id,
            DriverDocument.status != DocumentStatus.rejected,
        )
    )
    return list(result.scalars().all())


async def submit_document(
    db: AsyncSession,
    driver: Driver,
    document_type: DocumentType,
    data: bytes,
    document_number: str | None = None,
) -> DriverDocument:
    """Validate, upload, then write the row.

    ORDER MATTERS AND IS DELIBERATE. The object goes to Storage first and the
    row second, because a row pointing at an object that does not exist shows
    the reviewer a broken record, while an object with no row is invisible to
    everyone. Both are bad; only one is confusing.

    ACCEPTED DEBT: if the row write fails after a successful upload, the
    object is orphaned in the bucket and nothing cleans it up. That is the
    right trade for now — the alternative is a two-phase commit against
    someone else's storage service — and the retention deletion path walks
    rows, so an orphan would survive a driver's account closure. Worth a
    sweep if it ever happens more than theoretically.
    """
    content_type = validate_upload(data)

    existing = await _live_documents(db, driver.id)
    if any(d.document_type == document_type for d in existing):
        raise DocumentAlreadyPresent(document_type)

    path = storage.document_path(
        driver.id, document_type.value, uuid.uuid4().hex
    )
    await storage.default_storage_service().upload(path, data, content_type)

    document = DriverDocument(
        driver_id=driver.id,
        document_type=document_type,
        storage_path=path,
        document_number=document_number,
        status=DocumentStatus.submitted,
        uploaded_at=datetime.now(UTC),
    )
    db.add(document)

    try:
        await db.flush()
    except IntegrityError:
        # The partial unique index caught a race the check above missed: two
        # simultaneous uploads of the same type. Same reasoning as
        # claim_booking — the pre-check is for a friendly message, the index
        # is what actually enforces it.
        await db.rollback()
        raise DocumentAlreadyPresent(document_type)

    await _recompute_status(db, driver)
    await db.commit()
    await db.refresh(document)
    return document


async def _recompute_status(db: AsyncSession, driver: Driver) -> None:
    """A driver is `submitted` only when BOTH document types are present.

    Otherwise a driver who uploaded one licence would sit in the reviewer's
    queue with nothing to review. Never touches `approved` or writes
    is_verified — approval is a human act, not a derived one.
    """
    if driver.verification_status == VerificationStatus.approved:
        return

    live = await _live_documents(db, driver.id)
    have = {d.document_type for d in live}
    complete = have >= {DocumentType.driving_licence, DocumentType.vehicle_rc}

    driver.verification_status = (
        VerificationStatus.submitted if complete else VerificationStatus.pending
    )
    logger.info(
        "driver %s verification_status -> %s (%d/%d documents)",
        driver.id,
        driver.verification_status.value,
        len(have),
        len(DocumentType),
    )


async def list_documents(
    db: AsyncSession, driver_id: int
) -> list[DriverDocument]:
    """All documents including rejected ones, newest first — a driver needs to
    see the rejection reason against the thing that was rejected."""
    result = await db.execute(
        select(DriverDocument)
        .where(DriverDocument.driver_id == driver_id)
        .order_by(DriverDocument.id.desc())
    )
    return list(result.scalars().all())


async def _load_driver(db: AsyncSession, driver_id: int) -> Driver:
    driver = await db.get(Driver, driver_id)
    if driver is None:
        raise DriverNotFound()
    return driver


async def approve_driver(
    db: AsyncSession, driver_id: int, reviewed_by: str
) -> Driver:
    """The only place is_verified becomes true."""
    driver = await _load_driver(db, driver_id)
    now = datetime.now(UTC)

    for document in await _live_documents(db, driver.id):
        document.status = DocumentStatus.approved
        document.reviewed_at = now
        document.reviewed_by = reviewed_by
        document.rejection_reason = None

    driver.verification_status = VerificationStatus.approved
    driver.is_verified = True

    await db.commit()
    await db.refresh(driver)
    logger.info("driver %s APPROVED by %s", driver.id, reviewed_by)
    return driver


async def reject_driver(
    db: AsyncSession,
    driver_id: int,
    reason: str,
    document_types: list[DocumentType],
    reviewed_by: str,
) -> Driver:
    """Reject named documents with a reason the driver can act on.

    Only the named documents are rejected. A blurry licence should not force
    a driver to re-photograph an RC that was fine.
    """
    driver = await _load_driver(db, driver_id)
    now = datetime.now(UTC)

    for document in await _live_documents(db, driver.id):
        if document.document_type in document_types:
            document.status = DocumentStatus.rejected
            document.rejection_reason = reason
            document.reviewed_at = now
            document.reviewed_by = reviewed_by

    driver.verification_status = VerificationStatus.rejected
    # Explicit rather than left alone: a driver approved earlier and rejected
    # on a later resubmission must lose access, not keep it.
    driver.is_verified = False

    await db.commit()
    await db.refresh(driver)
    logger.info(
        "driver %s REJECTED by %s (%s)",
        driver.id,
        reviewed_by,
        ", ".join(d.value for d in document_types),
    )
    return driver


async def pending_drivers(db: AsyncSession) -> list[Driver]:
    result = await db.execute(
        select(Driver)
        .where(Driver.verification_status == VerificationStatus.submitted)
        .order_by(Driver.id)
    )
    return list(result.scalars().all())


async def delete_all_documents(db: AsyncSession, driver_id: int) -> int:
    """RETENTION. Deletes a driver's documents from Storage and the database.

    Under the DPDP Act personal data is retained for the purpose it was
    collected for and deleted when that purpose ends; indefinite storage is
    not a lawful default. These are licences and vehicle registrations — the
    most sensitive data VOLT holds — so the deletion path is part of the spec
    that introduced them rather than a cleanup task nobody gets to.

    Not scheduled. It exists, it is callable, and account closure is what
    calls it. Storage first, rows second: a row with no object is a broken
    record a reviewer can see, whereas a deleted object with a surviving row
    can be retried by running this again.

    Returns the number of rows removed.
    """
    documents = await list_documents(db, driver_id)
    service = storage.default_storage_service()

    for document in documents:
        await service.delete(document.storage_path)

    for document in documents:
        await db.delete(document)

    driver = await db.get(Driver, driver_id)
    if driver is not None:
        driver.verification_status = VerificationStatus.pending
        driver.is_verified = False

    await db.commit()
    logger.info("deleted %d documents for driver %s", len(documents), driver_id)
    return len(documents)
