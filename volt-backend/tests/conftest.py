import pytest
import pytest_asyncio

from app.database import engine
from app.services.booking import reset_expiry_throttle


@pytest.fixture(autouse=True)
def _reset_expiry_throttle():
    """expire_stale_bookings is throttled by module-level state, so without
    this the first test to sweep would suppress the sweep in every test that
    ran within the next minute — and which tests those are depends on
    ordering. Reset before each test so every one sees a fresh throttle."""
    reset_expiry_throttle()


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_after_test():
    """Each pytest-asyncio test gets its own event loop, but `engine` is a
    module-level singleton whose connection pool is tied to whichever loop
    created it. Without disposing it, the next test's loop tries to reuse a
    connection from a now-closed loop and blows up."""
    yield
    await engine.dispose()
