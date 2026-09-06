import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import TimestampMixin


class DocumentType(str, enum.Enum):
    """What a driver has to produce to be allowed to carry goods.

    Licence and RC prove the two things that actually matter: that the person
    may drive, and that the vehicle is theirs.

    AADHAAR IS DELIBERATELY ABSENT and must not be added here. Storing Aadhaar
    numbers or scans places a private entity under the Aadhaar Act and UIDAI's
    regulations — masking duties, language-specific consent, a Grievance
    Officer, breach reporting to UIDAI. The lawful route is authentication
    (DigiLocker, or eKYC via a licensed AUA/KUA), not collection. See
    docs/future-plans.md before reopening this.
    """

    driving_licence = "driving_licence"
    vehicle_rc = "vehicle_rc"


class DocumentStatus(str, enum.Enum):
    """Per-document review state.

    Note there is no `pending`: a row exists only once something has been
    uploaded, so `submitted` is the first state a document can be in. The
    driver-level `pending` (nothing uploaded yet) lives on Driver instead.
    """

    submitted = "submitted"
    approved = "approved"
    rejected = "rejected"


class DriverDocument(Base, TimestampMixin):
    """One uploaded document, and the audit trail of its review.

    The FILE is not here. The image lives in Firebase Storage and this row
    holds a reference to it, because a single row that carried both would be
    half-written whenever an upload failed.
    """

    __tablename__ = "driver_documents"

    id: Mapped[int] = mapped_column(primary_key=True)

    driver_id: Mapped[int] = mapped_column(
        ForeignKey("drivers.id"), nullable=False, index=True
    )

    document_type: Mapped[DocumentType] = mapped_column(
        Enum(DocumentType, name="document_type"), nullable=False
    )

    # The Storage object path, NOT a download URL. Signed URLs expire by
    # design; a path does not. It is also what makes a future bucket move a
    # one-column rewrite rather than a re-upload — see future-plans.md §12,
    # since the bucket is in US-EAST1 permanently.
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)

    # As TYPED BY THE DRIVER, for the reviewer to cross-check against the
    # image. Never trusted as verified data — it is a hint, not a fact, and
    # nothing in the system reads it except a human comparing it to a photo.
    document_number: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status"),
        nullable=False,
        default=DocumentStatus.submitted,
    )

    # Shown to the DRIVER, so it has to be usable: "licence photo is blurry",
    # not "invalid". A reason they cannot act on produces a resubmission of
    # the same unusable photo.
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Free text. There is no admin user table yet, and inventing one to hold a
    # single owner would be worse than recording who it was as a string.
    # Replaced when real admin auth arrives — see future-plans.md.
    reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)

    __table_args__ = (
        # One LIVE document per type per driver. Rejected rows are excluded so
        # a driver may resubmit, and the rejected original stays on the record
        # — which is the whole point if a rejection is ever disputed.
        Index(
            "one_live_document_per_driver_type",
            "driver_id",
            "document_type",
            unique=True,
            postgresql_where=text("status <> 'rejected'"),
        ),
    )
