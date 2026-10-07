"""Firebase Storage access for driver documents.

No new dependency: firebase-admin (already pinned for auth) bundles
google-cloud-storage, so `firebase_admin.storage` is importable as-is.

THE DRIVER APP NEVER TOUCHES STORAGE DIRECTLY. Uploads and reads both go
through this module using the service account, and the bucket rules deny
client access outright. A client that can write can usually be made to write
somewhere else, and nothing server-side would have validated what landed.

Every caller reaches the service through the MODULE
(`storage.default_storage_service()`), never a from-import. That is not
style — a from-import binds the name into the calling module at import time,
so patching it at its definition site does nothing. The routing spend guard
failed exactly that way and 49 tests hit a live billable API while the suite
looked green. Tests patch the factory below.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Protocol

from app.config import get_settings

logger = logging.getLogger(__name__)

# 15 minutes. Long enough for the reviewer to open the pending queue and work
# through a batch of images; short enough that a URL copied out of a browser
# history, a screenshot or a proxy log is useless by the time anyone finds it.
# These are licences and vehicle registrations — the URL is the only thing
# standing between the object and the public, so it should not outlive the
# sitting it was issued for.
SIGNED_URL_TTL = timedelta(minutes=15)

# 10 MiB. Modern phone cameras produce 2-8MB JPEGs and a scanned RC as PDF is
# usually under 2MB, so this accepts real documents from a real phone without
# asking the driver to compress anything. A cap that rejects a genuine photo
# is worse than no cap: the driver cannot proceed and has no idea why. The
# ceiling exists to stop someone uploading a film, not to economise.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class StorageNotConfigured(Exception):
    """Raised at STARTUP, not at upload time, and deliberately fatal.

    Distinct from StorageError: that one means a request failed and the caller
    gets a 503. This one means the process should not come up at all.

    It exists because of a real incident. The bucket name was never configured,
    firebase_admin was initialised without it, and nothing noticed until a
    driver pressed Upload in production — registration, /drivers/me and the
    documents list all worked, so the deploy looked healthy. Half-working is
    the worst outcome here: a driver gets through registration, is routed to
    the upload screen, and cannot finish, leaving a driver row with no
    documents and no way to make progress.

    On Render a startup failure keeps the PREVIOUS deploy serving, so failing
    here costs nothing and blocks the bad deploy — strictly better than
    shipping a backend that accepts drivers it cannot onboard.
    """


class StorageError(Exception):
    """Storage was reachable but refused, or is not configured.

    Deliberately NOT swallowed the way routing failures are. A fare can
    degrade to haversine and still be a fare; a document upload that silently
    fails leaves a driver believing they have submitted something. This
    surfaces as a 503 and the driver is told to try again.
    """


class StorageService(Protocol):
    async def upload(
        self, path: str, data: bytes, content_type: str
    ) -> None: ...

    async def signed_url(self, path: str) -> str: ...

    async def delete(self, path: str) -> None: ...


def document_path(driver_id: int, document_type: str, token: str) -> str:
    """`driver-documents/{driver_id}/{document_type}/{uuid}`.

    The uuid is why a resubmission never overwrites the rejected original,
    which is the whole point if a rejection is ever disputed — the old image
    is still there to look at next to the reason it was refused.
    """
    return f"driver-documents/{driver_id}/{document_type}/{token}"


class FirebaseStorageService:
    """The real thing. Imports firebase_admin lazily so that a process with no
    credentials can still import this module — the test suite does exactly
    that, and so does anyone running the app without Storage configured."""

    async def upload(self, path: str, data: bytes, content_type: str) -> None:
        blob = self._blob(path)
        try:
            blob.upload_from_string(data, content_type=content_type)
        except Exception as e:  # noqa: BLE001 - surfaced as 503, see StorageError
            logger.error("storage upload failed for %s: %s", path, e)
            raise StorageError("Could not store the document") from e

    async def signed_url(self, path: str) -> str:
        blob = self._blob(path)
        try:
            return blob.generate_signed_url(expiration=SIGNED_URL_TTL, version="v4")
        except Exception as e:  # noqa: BLE001
            logger.error("signed url failed for %s: %s", path, e)
            raise StorageError("Could not produce a document link") from e

    async def delete(self, path: str) -> None:
        blob = self._blob(path)
        try:
            # A missing object is a success for our purposes: the caller wants
            # it gone, and retention deletion must be idempotent so a partial
            # failure can simply be re-run.
            blob.delete(if_generation_match=None)
        except Exception as e:  # noqa: BLE001
            if "404" in str(e) or "No such object" in str(e):
                logger.info("storage delete: %s was already gone", path)
                return
            logger.error("storage delete failed for %s: %s", path, e)
            raise StorageError("Could not delete the document") from e

    @staticmethod
    def _blob(path: str):
        try:
            from firebase_admin import storage as fb_storage
        except ImportError as e:  # pragma: no cover - firebase-admin is pinned
            raise StorageError("Firebase Storage is not available") from e
        try:
            return fb_storage.bucket().blob(path)
        except Exception as e:  # noqa: BLE001
            # Most likely cause: firebase_admin was initialised without a
            # storageBucket, or credentials are missing entirely.
            logger.error("storage bucket unavailable: %s", e)
            raise StorageError("Storage is not configured") from e


def verify_storage_configured() -> None:
    """Startup check. Fails the process when the bucket name is missing.

    TWO CHECKS WITH DELIBERATELY DIFFERENT SEVERITY:

    1. A MISSING BUCKET NAME IS FATAL. It is pure configuration — no network,
       no credentials, the same answer every time — so there is no reading of
       it other than "this deploy is misconfigured". This alone would have
       caught the incident this function exists for.

    2. AN UNREACHABLE BUCKET ONLY LOGS. Tempting to make fatal, and wrong on
       this host: Render's free plan spins the service down when idle and runs
       lifespan again on every cold start. A fatal network probe would turn a
       momentary Google blip into an outage of the whole API — bookings and
       fares included — rather than a failed deploy. A name that is set but
       wrong is a smaller, rarer problem than that, and it still gets an ERROR
       in the logs to find it by.
    """
    settings = get_settings()

    if not settings.firebase_storage_bucket:
        raise StorageNotConfigured(
            "FIREBASE_STORAGE_BUCKET is not set. Driver document upload "
            "(spec 017) cannot work without it, and the failure would not "
            "appear until a driver pressed Upload. Set it to the bucket from "
            "the Firebase console, e.g. volt-2b36f.firebasestorage.app."
        )

    try:
        from firebase_admin import storage as fb_storage

        bucket = fb_storage.bucket()
        reachable = bucket.exists()
    except Exception as e:  # noqa: BLE001 - see docstring: never fatal
        logger.error(
            "storage configured as %s but could not be reached at startup: %s",
            settings.firebase_storage_bucket,
            e,
        )
        return

    if not reachable:
        logger.error(
            "storage bucket %s does not exist. Document upload will 503.",
            settings.firebase_storage_bucket,
        )
        return

    logger.info("storage ready: %s", settings.firebase_storage_bucket)


def default_storage_service() -> StorageService:
    """The service every caller uses.

    One factory rather than each caller constructing its own, for one concrete
    reason: it gives the test suite exactly one seam to close. Add a caller
    that instantiates FirebaseStorageService() directly and the tests will
    reach real Storage.
    """
    return FirebaseStorageService()
