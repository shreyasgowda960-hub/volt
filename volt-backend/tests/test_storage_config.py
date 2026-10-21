"""Storage CONFIGURATION, which nothing else in this suite can reach.

Why these tests did not exist, and why that was structural rather than an
oversight worth shrugging at:

conftest's autouse `_block_outbound_storage` replaces
`app.services.storage.default_storage_service` wholesale, so no test ever
constructs `FirebaseStorageService` and `_blob()` — the single line that
resolves the bucket name — is never executed by the suite. That guard is
correct and must stay: a green test run must not be able to create an orphaned
"licence" in production storage. But the guard and the coverage are the SAME
patch, so making Storage safe to test also made it impossible to test.

The consequence was a real incident. The bucket name was never configured
anywhere, 216 tests passed, the deploy was healthy, registration and the
documents list both worked, and the first person to discover it was a driver
pressing Upload in production.

The way out is not to loosen the guard. It is to test the configuration
directly — no network, no real client — so the thing the guard hides is
asserted somewhere else.
"""

from unittest.mock import MagicMock, patch

import pytest

from pydantic import ValidationError

from app.config import MissingConfiguration, Settings, get_settings
from app.services.storage import verify_storage_configured


def _settings(**overrides) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://u:p@localhost/db",
        "firebase_storage_bucket": "volt-test.firebasestorage.app",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class TestTheBucketNameIsRequiredByTheType:
    """Enforcement lives in Settings, and ONLY in Settings.

    It used to live in a comment, in the type (as optional) and in a startup
    check, which is three places free to disagree. A required non-empty str
    fails when configuration is first loaded — earlier than any startup check
    can run, and earlier than the app finishes importing.

    _env_file=None is load-bearing in these tests: without it pydantic reads
    the developer's own .env, which does have a bucket, and every one of them
    would pass while asserting nothing.
    """

    BASE = {"database_url": "postgresql+asyncpg://u:p@localhost/db"}

    def test_a_missing_bucket_is_rejected(self, monkeypatch):
        monkeypatch.delenv("FIREBASE_STORAGE_BUCKET", raising=False)

        with pytest.raises(ValidationError) as exc_info:
            Settings(**self.BASE, _env_file=None)  # type: ignore[arg-type]

        assert any(
            err["loc"] == ("firebase_storage_bucket",)
            for err in exc_info.value.errors()
        )

    def test_an_empty_bucket_is_rejected(self, monkeypatch):
        """The shape a half-filled dashboard produces. `str` alone accepts it,
        which is why the field carries min_length=1."""
        monkeypatch.delenv("FIREBASE_STORAGE_BUCKET", raising=False)

        with pytest.raises(ValidationError):
            Settings(  # type: ignore[arg-type]
                **self.BASE, firebase_storage_bucket="", _env_file=None
            )

    def test_the_failure_names_the_variable_and_the_file(self, monkeypatch):
        """A pydantic traceback is the wrong thing to hand someone who has
        just cloned the repo. get_settings turns it into a sentence."""
        monkeypatch.delenv("FIREBASE_STORAGE_BUCKET", raising=False)
        monkeypatch.setattr(
            "app.config.Settings",
            lambda *a, **kw: Settings(**self.BASE, _env_file=None),  # type: ignore[arg-type]
        )
        get_settings.cache_clear()

        try:
            with pytest.raises(MissingConfiguration) as exc_info:
                get_settings()
        finally:
            get_settings.cache_clear()

        message = str(exc_info.value)
        assert "FIREBASE_STORAGE_BUCKET" in message
        assert ".env.example" in message


class TestReachabilityNeverStopsTheProcess:
    """The deliberate asymmetry, documented in verify_storage_configured.

    Render's free plan runs lifespan on every cold start, so a fatal network
    probe would convert a momentary Google blip into an outage of the entire
    API — bookings and fares included — rather than a failed deploy.
    """

    def test_an_unreachable_bucket_logs_and_continues(self, caplog):
        with patch(
            "app.services.storage.get_settings", return_value=_settings()
        ):
            with patch(
                "firebase_admin.storage.bucket",
                side_effect=RuntimeError("transient"),
            ):
                verify_storage_configured()  # must not raise

        assert "could not be reached" in caplog.text

    def test_a_bucket_that_does_not_exist_logs_and_continues(self, caplog):
        fake_bucket = MagicMock()
        fake_bucket.exists.return_value = False

        with patch(
            "app.services.storage.get_settings", return_value=_settings()
        ):
            with patch("firebase_admin.storage.bucket", return_value=fake_bucket):
                verify_storage_configured()  # must not raise

        assert "does not exist" in caplog.text

    def test_a_reachable_bucket_passes_quietly(self):
        fake_bucket = MagicMock()
        fake_bucket.exists.return_value = True

        with patch(
            "app.services.storage.get_settings", return_value=_settings()
        ):
            with patch("firebase_admin.storage.bucket", return_value=fake_bucket):
                verify_storage_configured()


class TestTheBucketNameReachesFirebase:
    """The other half of the incident.

    Checking the setting exists proves nothing if nobody passes it to
    firebase_admin — that was the actual defect: the setting did not exist AND
    initialize_app() was called with no options at all.
    """

    def test_init_firebase_passes_storage_bucket_as_an_option(self):
        """Passed unconditionally — Settings guarantees a non-empty value, so
        there is no unset case left for init_firebase to branch on."""
        import app.auth as auth_module

        with patch.object(auth_module, "firebase_admin") as fb:
            fb._apps = {}
            with patch.object(
                auth_module.credentials, "Certificate", return_value="cred"
            ):
                with patch.object(
                    auth_module,
                    "get_settings",
                    return_value=_settings(
                        firebase_credentials_json=None,
                        firebase_storage_bucket="volt-test.firebasestorage.app",
                    ),
                ):
                    auth_module.init_firebase()

        fb.initialize_app.assert_called_once()
        _, options = fb.initialize_app.call_args[0]
        assert options["storageBucket"] == "volt-test.firebasestorage.app"


class TestSignedUrlExpiry:
    """What expiry the URLs we hand a reviewer actually carry.

    Exercises the REAL FirebaseStorageService.signed_url against a real
    google-cloud-storage Bucket. Only the credentials are throwaway: V4 signing
    is a purely local operation, so a locally generated RSA key produces a
    structurally genuine URL without a network call, a real service account, or
    any risk of touching production storage.

    cryptography is not a new dependency — google-cloud-storage already
    requires it for exactly this signing path, so our signed_url cannot work
    without it in the first place.

    WHAT THIS CANNOT PROVE: that Google honours the expiry. That needs a valid
    service account key and a real object, and is a manual check. What it does
    prove is the claim we control — that the URL says 15 minutes, and that the
    expiry is inside the signed material rather than an editable query param.
    """

    @staticmethod
    def _throwaway_bucket():
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from google.cloud import storage as gcs
        from google.oauth2 import service_account

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        creds = service_account.Credentials.from_service_account_info(
            {
                "type": "service_account",
                "project_id": "volt-test",
                "private_key_id": "throwaway",
                "private_key": pem,
                "client_email": "throwaway@volt-test.iam.gserviceaccount.com",
                "client_id": "0",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        )
        client = gcs.Client(project="volt-test", credentials=creds)
        return client.bucket("volt-test.firebasestorage.app")

    def _sign(self, path: str) -> str:
        import asyncio

        from app.services.storage import FirebaseStorageService

        with patch(
            "firebase_admin.storage.bucket", return_value=self._throwaway_bucket()
        ):
            return asyncio.run(FirebaseStorageService().signed_url(path))

    def test_the_url_expires_in_fifteen_minutes(self):
        import urllib.parse

        from app.services.storage import SIGNED_URL_TTL

        url = self._sign("driver-documents/42/driving_licence/abc")
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))

        assert int(query["X-Goog-Expires"]) == 900
        # And that the constant is what produced it, so changing SIGNED_URL_TTL
        # without meaning to cannot leave this test passing on a stale number.
        assert int(query["X-Goog-Expires"]) == int(SIGNED_URL_TTL.total_seconds())

    def test_the_expiry_is_signed_not_merely_attached(self):
        """A reviewer could otherwise extend their own link by editing it.

        V4 puts the query string into the string-to-sign, so X-Goog-Expires is
        covered by X-Goog-Signature. Asserting the algorithm is V4 is what
        makes the 15 minutes above mean anything — a scheme that left the
        expiry outside the signature would read identically.
        """
        import urllib.parse

        url = self._sign("driver-documents/42/vehicle_rc/def")
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))

        assert query["X-Goog-Algorithm"] == "GOOG4-RSA-SHA256"
        assert query["X-Goog-Signature"]
        assert "X-Goog-Expires" in query

    def test_signed_urls_bypass_storage_rules_by_design(self):
        """The reason `allow read: if false` does not break the reviewer.

        A signed URL is served by storage.googleapis.com and authorised by the
        signature under IAM — Firebase Security Rules are not consulted at all.
        That is what lets the rules deny every client while the admin endpoint
        still shows images. If this ever starts pointing at
        firebasestorage.googleapis.com, the rules WOULD apply and every signed
        URL would 403.
        """
        import urllib.parse

        url = self._sign("driver-documents/42/driving_licence/ghi")
        assert urllib.parse.urlparse(url).netloc == "storage.googleapis.com"
