from app.config import Settings


def _url(raw: str) -> str:
    return Settings(database_url=raw).database_url


def test_plain_postgresql_scheme_gets_asyncpg_driver():
    assert _url("postgresql://u:p@host:5432/db") == "postgresql+asyncpg://u:p@host:5432/db"


def test_legacy_postgres_scheme_gets_asyncpg_driver():
    assert _url("postgres://u:p@host:5432/db") == "postgresql+asyncpg://u:p@host:5432/db"


def test_sslmode_query_param_is_stripped():
    assert _url("postgresql://u:p@host:5432/db?sslmode=require") == (
        "postgresql+asyncpg://u:p@host:5432/db"
    )


def test_already_correct_url_passes_through_unchanged():
    url = "postgresql+asyncpg://u:p@host:5432/db"
    assert _url(url) == url


def test_sslmode_stripped_while_other_query_params_survive():
    assert _url("postgresql://u:p@host:5432/db?sslmode=require&other=1") == (
        "postgresql+asyncpg://u:p@host:5432/db?other=1"
    )
