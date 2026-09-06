from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.driver import VerificationStatus
from app.models.driver_document import DocumentStatus, DocumentType


class DriverDocumentResponse(BaseModel):
    """What the DRIVER sees about their own document.

    NOTE THE ABSENCE OF A URL, and of storage_path. A driver has no need to
    re-read their own upload — they took the photo — and issuing signed URLs
    on this endpoint would widen the surface for nothing. storage_path is
    internal plumbing; leaking it tells a caller the bucket layout.

    Signed URLs appear on the ADMIN response only. There is a test that
    asserts this, and a grep, because the shape of mistake here is the same as
    the driver-sees-no-customer-data one in spec 011.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    document_type: DocumentType
    status: DocumentStatus
    document_number: str | None
    rejection_reason: str | None
    uploaded_at: datetime | None
    reviewed_at: datetime | None


class DriverDocumentsResponse(BaseModel):
    """The driver's own verification state, in one call.

    verification_status rides along because it is what the driver app routes
    on, and a second request to /drivers/me to learn it would be a round trip
    for a field we already have in hand.
    """

    verification_status: VerificationStatus
    documents: list[DriverDocumentResponse]


# --- Admin ---------------------------------------------------------------


class AdminDocumentResponse(DriverDocumentResponse):
    """The reviewer's view: everything the driver sees, plus a short-lived
    signed URL to the actual image. This is the only schema that carries one."""

    signed_url: str


class AdminPendingDriverResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: str
    vehicle_number: str
    vehicle_type_code: str
    verification_status: VerificationStatus
    documents: list[AdminDocumentResponse]


class RejectRequest(BaseModel):
    """A rejection the driver can act on.

    min_length is 10 rather than 1 deliberately: "invalid" is a legal string
    and a useless one. The reason is shown to the driver, and a reason they
    cannot act on produces a resubmission of the same unusable photo.
    """

    reason: str = Field(min_length=10, max_length=500)

    # Which documents failed. A blurry licence must not force a driver to
    # re-photograph an RC that was fine.
    document_types: list[DocumentType] = Field(min_length=1)
