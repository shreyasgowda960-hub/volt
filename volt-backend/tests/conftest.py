import pytest_asyncio

from app.database import engine


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_after_test():
    """Each pytest-asyncio test gets its own event loop, but `engine` is a
    module-level singleton whose connection pool is tied to whichever loop
    created it. Without disposing it, the next test's loop tries to reuse a
    connection from a now-closed loop and blows up."""
    yield
    await engine.dispose()
