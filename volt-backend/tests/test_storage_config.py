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

from app.config import Settings
from app.services.storage import (
    StorageNotConfigured,
    verify_storage_configured,
)


def _settings(**overrides) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://u:p@localhost/db",
        "firebase_storage_bucket": "volt-test.firebasestorage.app",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class TestMissingBucketIsFatal:
    """The one check that would have caught the incident outright."""

    def test_unset_bucket_raises(self):
        with patch(
            "app.services.storage.get_settings",
            return_value=_settings(firebase_storage_bucket=None),
        ):
            with pytest.raises(StorageNotConfigured) as exc_info:
                verify_storage_configured()

        # The message has to name the variable. Whoever hits this is reading a
        # Render deploy log, not this file.
        assert "FIREBASE_STORAGE_BUCKET" in str(exc_info.value)

    def test_empty_string_is_treated_as_unset(self):
        """An env var set to "" is the shape a half-filled dashboard produces,
        and it must not read as configured."""
        with patch(
            "app.services.storage.get_settings",
            return_value=_settings(firebase_storage_bucket=""),
        ):
            with pytest.raises(StorageNotConfigured):
                verify_storage_configured()

    def test_no_network_call_is_made_when_the_name_is_missing(self):
        """Fails on configuration alone.

        If this check needed Storage to answer, it could not be trusted to run
        on a cold start — which is exactly when it runs on Render's free plan.
        """
        with patch(
            "app.services.storage.get_settings",
            return_value=_settings(firebase_storage_bucket=None),
        ):
            with patch("firebase_admin.storage.bucket") as bucket:
                with pytest.raises(StorageNotConfigured):
                    verify_storage_configured()

        bucket.assert_not_called()


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

    def test_no_bucket_option_when_unset_rather_than_an_empty_one(self):
        """firebase_admin treats an empty storageBucket as a configured bucket
        with an empty name, which fails later and more confusingly than not
        setting the key at all."""
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
                        firebase_storage_bucket=None,
                    ),
                ):
                    auth_module.init_firebase()

        _, options = fb.initialize_app.call_args[0]
        assert "storageBucket" not in options
