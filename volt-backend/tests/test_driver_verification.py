"""Spec 017 — driver document verification.

The load-bearing assertion in this file is the FIRST one: an unverified driver
cannot claim a job. Everything else is about getting verified correctly; that
one is about what verification is FOR. Before spec 017 registration hardcoded
is_verified=True, so any phone number could register and immediately take
work.

Firebase Storage is never touched: conftest's autouse _block_outbound_storage
patches app.services.storage.default_storage_service. Patched through the
MODULE, not a from-imported name — the routing spend guard failed exactly that
way and let 49 tests hit a live billable API while the suite looked green.
"""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.database import SessionLocal
from app.main import app
from app.models.booking import Booking
from app.models.driver import Driver, VerificationStatus
from app.models.driver_document import (
    DocumentStatus,
    DocumentType,
    DriverDocument,
)
from app.models.user import User
from helpers import (
    ADMIN_HEADERS,
    JPEG_BYTES,
    NOT_AN_IMAGE,
    PNG_BYTES,
    approve_driver_via_admin,
)

_AUTH_HEADERS = {"Authorization": "Bearer whatever"}

_REGISTER_PAYLOAD = {
    "name": "Doc Driver",
    "vehicle_number": "KA 05 DV 4321",
    "vehicle_type_code": "bike",
}

_BOOKING_PAYLOAD = {
    "pickup": {"address": "Koramangala", "lat": 12.9352, "lng": 77.6245},
    "drop": {"address": "Whitefield", "lat": 12.9698, "lng": 77.75},
    "vehicle_type_code": "bike",
    "goods_description": "Test parcel",
    "approx_weight_kg": 5,
    "payment_method": "cash",
}


def _mock_token(uid: str, phone: str):
    return patch(
        "app.auth.firebase_auth.verify_id_token",
        return_value={"uid": uid, "phone_number": phone},
    )


async def _cleanup(phone: str) -> None:
    async with SessionLocal() as db:
        driver_id = (
            await db.execute(select(Driver.id).where(Driver.phone == phone))
        ).scalar_one_or_none()
        if driver_id is not None:
            # Documents and bookings both reference drivers.id; the FK blocks
            # deleting the driver until they are gone.
            await db.execute(
                delete(DriverDocument).where(
                    DriverDocument.driver_id == driver_id
                )
            )
            await db.execute(delete(Booking).where(Booking.driver_id == driver_id))
            await db.execute(delete(Driver).where(Driver.id == driver_id))
        user_id = (
            await db.execute(select(User.id).where(User.phone == phone))
        ).scalar_one_or_none()
        if user_id is not None:
            await db.execute(delete(Booking).where(Booking.customer_id == user_id))
            await db.execute(delete(User).where(User.id == user_id))
        await db.commit()


def _upload(client, doc_type: str, data: bytes, declared: str = "image/jpeg"):
    """Upload as multipart.

    `declared` is deliberately a parameter and deliberately lied about in one
    test: the declared content type is caller-controlled, so the server has to
    sniff the bytes.
    """
    return client.post(
        "/api/v1/drivers/me/documents",
        headers=_AUTH_HEADERS,
        data={"document_type": doc_type},
        files={"file": (f"{doc_type}.jpg", data, declared)},
    )


async def _register(client, uid: str, phone: str) -> int:
    resp = await client.post(
        "/api/v1/drivers/register",
        json=_REGISTER_PAYLOAD,
        headers=_AUTH_HEADERS,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# --- The point of the whole spec ----------------------------------------


@pytest.mark.asyncio
async def test_unverified_driver_cannot_claim_a_job():
    """THE assertion. A regression in get_current_driver fails here.

    Deliberately asserted through the HTTP path rather than by calling the
    dependency, because the thing that matters is that the ENDPOINT refuses —
    a dependency that returns correctly but is wired to the wrong routes would
    pass a unit test and lose money.
    """
    driver_phone = "+919000009101"
    customer_phone = "+919000009102"
    await _cleanup(driver_phone)
    await _cleanup(customer_phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-unverified-claim-c", customer_phone):
            created = await client.post(
                "/api/v1/bookings", json=_BOOKING_PAYLOAD, headers=_AUTH_HEADERS
            )
            assert created.status_code == 201
            code = created.json()["public_code"]

        with _mock_token("uid-unverified-claim-d", driver_phone):
            await _register(client, "uid-unverified-claim-d", driver_phone)

            # Unverified: every operational endpoint must refuse.
            jobs = await client.get("/api/v1/drivers/jobs", headers=_AUTH_HEADERS)
            accept = await client.post(
                f"/api/v1/bookings/{code}/accept", headers=_AUTH_HEADERS
            )

    assert jobs.status_code == 403
    assert accept.status_code == 403
    assert "pending verification" in accept.json()["detail"]

    await _cleanup(driver_phone)
    await _cleanup(customer_phone)


@pytest.mark.asyncio
async def test_unverified_driver_can_still_read_its_own_profile_and_documents():
    """The circular-dependency fix.

    A pending driver MUST be able to read verification_status, or the app can
    never route them to the upload screen — they would need to be verified to
    discover that they are not verified.
    """
    phone = "+919000009103"
    await _cleanup(phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-unverified-read", phone):
            await _register(client, "uid-unverified-read", phone)
            me = await client.get("/api/v1/drivers/me", headers=_AUTH_HEADERS)
            docs = await client.get(
                "/api/v1/drivers/me/documents", headers=_AUTH_HEADERS
            )

    assert me.status_code == 200
    assert me.json()["verification_status"] == "pending"
    assert docs.status_code == 200
    assert docs.json()["documents"] == []

    await _cleanup(phone)


# --- Upload validation ---------------------------------------------------


@pytest.mark.asyncio
async def test_upload_rejected_when_bytes_are_not_an_image():
    """Declared image/jpeg, actually a PE executable.

    The declared content type is caller-controlled and means nothing. If this
    test ever passes with NOT_AN_IMAGE accepted, the server is trusting the
    request header.
    """
    phone = "+919000009104"
    await _cleanup(phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-bad-bytes", phone):
            await _register(client, "uid-bad-bytes", phone)
            resp = await _upload(
                client, "driving_licence", NOT_AN_IMAGE, declared="image/jpeg"
            )

    assert resp.status_code == 422
    assert "JPG, PNG or PDF" in resp.json()["detail"]

    await _cleanup(phone)


@pytest.mark.asyncio
async def test_upload_rejected_when_one_is_already_submitted():
    phone = "+919000009105"
    await _cleanup(phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-dup-upload", phone):
            await _register(client, "uid-dup-upload", phone)
            first = await _upload(client, "driving_licence", JPEG_BYTES)
            second = await _upload(client, "driving_licence", PNG_BYTES)

    assert first.status_code == 201
    assert second.status_code == 409
    assert "already" in second.json()["detail"]

    await _cleanup(phone)


@pytest.mark.asyncio
async def test_status_becomes_submitted_only_when_both_documents_exist():
    """One document is not a queue entry.

    A driver who uploaded only a licence must stay `pending`, or the reviewer
    opens the queue and finds nothing to review.
    """
    phone = "+919000009106"
    await _cleanup(phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-both-docs", phone):
            await _register(client, "uid-both-docs", phone)

            await _upload(client, "driving_licence", JPEG_BYTES)
            after_one = await client.get(
                "/api/v1/drivers/me/documents", headers=_AUTH_HEADERS
            )

            await _upload(client, "vehicle_rc", PNG_BYTES)
            after_both = await client.get(
                "/api/v1/drivers/me/documents", headers=_AUTH_HEADERS
            )

    assert after_one.json()["verification_status"] == "pending"
    assert after_both.json()["verification_status"] == "submitted"
    assert len(after_both.json()["documents"]) == 2

    await _cleanup(phone)


# --- Review --------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_verifies_and_reject_unverifies_with_a_reason():
    phone = "+919000009107"
    await _cleanup(phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-approve-reject", phone):
            driver_id = await _register(client, "uid-approve-reject", phone)
            await _upload(client, "driving_licence", JPEG_BYTES)
            await _upload(client, "vehicle_rc", PNG_BYTES)

        approved = await client.post(
            f"/api/v1/admin/drivers/{driver_id}/approve", headers=ADMIN_HEADERS
        )
        assert approved.status_code == 200
        assert approved.json()["is_verified"] is True
        assert approved.json()["verification_status"] == "approved"

        rejected = await client.post(
            f"/api/v1/admin/drivers/{driver_id}/reject",
            headers=ADMIN_HEADERS,
            json={
                "reason": "Licence photo is blurry, please retake it in daylight",
                "document_types": ["driving_licence"],
            },
        )
        assert rejected.status_code == 200
        # An approved driver who fails a later review must LOSE access, not
        # keep it.
        assert rejected.json()["is_verified"] is False
        assert rejected.json()["verification_status"] == "rejected"

        with _mock_token("uid-approve-reject", phone):
            docs = await client.get(
                "/api/v1/drivers/me/documents", headers=_AUTH_HEADERS
            )

    licence = [
        d for d in docs.json()["documents"] if d["document_type"] == "driving_licence"
    ][0]
    assert licence["status"] == "rejected"
    assert "blurry" in licence["rejection_reason"]

    await _cleanup(phone)


@pytest.mark.asyncio
async def test_rejected_driver_can_resubmit_and_the_old_row_remains():
    """The state machine loops, and the rejected original is kept.

    Keeping it matters if a rejection is ever disputed: the image that was
    refused is still there next to the reason it was refused. The uuid in the
    storage path is what makes that possible — a resubmission never overwrites.
    """
    phone = "+919000009108"
    await _cleanup(phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-resubmit", phone):
            driver_id = await _register(client, "uid-resubmit", phone)
            await _upload(client, "driving_licence", JPEG_BYTES)
            await _upload(client, "vehicle_rc", PNG_BYTES)

        await client.post(
            f"/api/v1/admin/drivers/{driver_id}/reject",
            headers=ADMIN_HEADERS,
            json={
                "reason": "Licence photo is cut off at the edges, retake it",
                "document_types": ["driving_licence"],
            },
        )

        with _mock_token("uid-resubmit", phone):
            resubmitted = await _upload(client, "driving_licence", PNG_BYTES)
            docs = await client.get(
                "/api/v1/drivers/me/documents", headers=_AUTH_HEADERS
            )

    assert resubmitted.status_code == 201

    licences = [
        d for d in docs.json()["documents"] if d["document_type"] == "driving_licence"
    ]
    assert len(licences) == 2, "the rejected original must survive"
    assert {d["status"] for d in licences} == {"rejected", "submitted"}
    # Both documents live again, so the driver is back in the queue.
    assert docs.json()["verification_status"] == "submitted"

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(DriverDocument.storage_path).where(
                    DriverDocument.driver_id == driver_id,
                    DriverDocument.document_type == DocumentType.driving_licence,
                )
            )
        ).scalars().all()
    assert len(set(rows)) == 2, "resubmission must not reuse the storage path"

    await _cleanup(phone)


@pytest.mark.asyncio
async def test_review_endpoints_require_the_admin_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        no_header = await client.get("/api/v1/admin/drivers/pending")
        wrong = await client.get(
            "/api/v1/admin/drivers/pending",
            headers={"X-Admin-Token": "not-the-token"},
        )
        approve = await client.post("/api/v1/admin/drivers/1/approve")
        reject = await client.post(
            "/api/v1/admin/drivers/1/reject",
            json={"reason": "a reason long enough", "document_types": ["vehicle_rc"]},
        )
        delete_docs = await client.delete("/api/v1/admin/drivers/1/documents")

    for name, resp in [
        ("pending, no header", no_header),
        ("pending, wrong token", wrong),
        ("approve", approve),
        ("reject", reject),
        ("delete", delete_docs),
    ]:
        assert resp.status_code == 401, f"{name} returned {resp.status_code}"


# --- Signed URLs are admin-only -----------------------------------------


@pytest.mark.asyncio
async def test_signed_urls_appear_only_on_admin_responses():
    """Same shape as the driver-sees-no-customer-data assertion in spec 011.

    A signed URL is the ONLY way to read a document — Storage rules deny all
    client access — so leaking one onto a driver-facing response is the whole
    exposure, not a cosmetic slip.
    """
    phone = "+919000009109"
    await _cleanup(phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-signed-urls", phone):
            await _register(client, "uid-signed-urls", phone)
            await _upload(client, "driving_licence", JPEG_BYTES)
            await _upload(client, "vehicle_rc", PNG_BYTES)
            driver_view = await client.get(
                "/api/v1/drivers/me/documents", headers=_AUTH_HEADERS
            )

        admin_view = await client.get(
            "/api/v1/admin/drivers/pending", headers=ADMIN_HEADERS
        )

    # The driver's own view carries status and reasons, and no way in.
    body = driver_view.text
    assert "signed_url" not in body
    assert "storage_path" not in body
    assert "storage.test.invalid" not in body
    for document in driver_view.json()["documents"]:
        assert set(document) == {
            "id",
            "document_type",
            "status",
            "document_number",
            "rejection_reason",
            "uploaded_at",
            "reviewed_at",
        }

    # The reviewer's view does.
    assert admin_view.status_code == 200
    mine = [d for d in admin_view.json() if d["phone"] == phone]
    assert len(mine) == 1, "a submitted driver must appear in the queue"
    assert len(mine[0]["documents"]) == 2
    for document in mine[0]["documents"]:
        assert document["signed_url"].startswith("https://")

    await _cleanup(phone)


# --- Retention -----------------------------------------------------------


@pytest.mark.asyncio
async def test_deleting_documents_clears_storage_and_rows_and_resets_the_driver():
    """The DPDP retention path. Callable, not scheduled — see spec 017 step 7.

    Asserts on the fake storage service's recorded deletions, so this proves
    the objects are removed and not merely the rows: a row-only delete would
    leave a licence in the bucket with nothing pointing at it, which is the
    worst of both outcomes.
    """
    import conftest

    phone = "+919000009110"
    await _cleanup(phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-retention", phone):
            driver_id = await _register(client, "uid-retention", phone)
            await _upload(client, "driving_licence", JPEG_BYTES)
            await _upload(client, "vehicle_rc", PNG_BYTES)

        await approve_driver_via_admin(client, driver_id)
        stored_paths = set(conftest.fake_storage.uploaded)
        assert len(stored_paths) == 2

        deleted = await client.delete(
            f"/api/v1/admin/drivers/{driver_id}/documents", headers=ADMIN_HEADERS
        )

    assert deleted.status_code == 200
    assert deleted.json()["documents_deleted"] == 2
    assert set(conftest.fake_storage.deleted) == stored_paths
    assert conftest.fake_storage.uploaded == {}

    async with SessionLocal() as db:
        remaining = (
            await db.execute(
                select(DriverDocument).where(
                    DriverDocument.driver_id == driver_id
                )
            )
        ).scalars().all()
        driver = await db.get(Driver, driver_id)
        assert remaining == []
        # Deleting the evidence must revoke the verification it supported.
        assert driver.verification_status == VerificationStatus.pending
        assert driver.is_verified is False

    await _cleanup(phone)


# --- Unit-level: the byte sniffing itself --------------------------------


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (JPEG_BYTES, "image/jpeg"),
        (PNG_BYTES, "image/png"),
        (b"%PDF-1.4\n%%EOF", "application/pdf"),
    ],
)
def test_sniff_accepts_the_three_real_formats(data, expected):
    from app.services.driver_verification import sniff_content_type

    assert sniff_content_type(data) == expected


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"MZ\x90\x00",  # PE executable
        b"GIF89a",  # a real image format, still not accepted
        b"\x1f\x8b\x08",  # gzip
        b"<?xml version='1.0'?>",
        b"\xff\xd8",  # truncated JPEG signature
    ],
)
def test_sniff_rejects_everything_else(data):
    from app.services.driver_verification import UnsupportedDocumentFormat, sniff_content_type

    with pytest.raises(UnsupportedDocumentFormat):
        sniff_content_type(data)


def test_document_status_has_no_pending_value():
    """A row exists only once something was uploaded, so `submitted` is the
    first state a DOCUMENT can be in. Driver-level `pending` means "nothing
    uploaded" and lives on Driver. Collapsing the two would make an empty
    queue indistinguishable from an unreviewed one."""
    assert set(DocumentStatus) == {
        DocumentStatus.submitted,
        DocumentStatus.approved,
        DocumentStatus.rejected,
    }


def test_aadhaar_is_not_a_document_type():
    """Guardrail, asserted rather than trusted to a comment.

    Storing Aadhaar places a private entity under the Aadhaar Act and UIDAI's
    regulations. Licence and RC prove what matters for goods delivery — that
    the person may drive and the vehicle is theirs. Aadhaar proves neither.
    See docs/future-plans.md before touching this.
    """
    assert set(DocumentType) == {
        DocumentType.driving_licence,
        DocumentType.vehicle_rc,
    }
    assert not any("aadhaar" in t.value.lower() for t in DocumentType)
