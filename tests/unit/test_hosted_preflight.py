import pytest

from apps.cli.check_hosted import validate_url


@pytest.mark.parametrize(
    "value",
    [
        "postgresql://user:example@db.example.invalid/postgres",
        "postgresql://user:example@db.example.invalid/postgres?sslmode=disable",
        "postgresql://user:example@db.example.invalid:6543/postgres?sslmode=require",
        "sqlite:///local.db",
    ],
)
def test_hosted_preflight_refuses_insecure_or_incompatible_connections(value):
    with pytest.raises(ValueError):
        validate_url(value)


def test_hosted_preflight_preserves_encoded_credentials_and_tls_settings():
    url = validate_url(
        "postgresql://memory_app.project:encoded%40value@pool.example.invalid:5432/postgres?sslmode=require"
    )
    assert url.drivername == "postgresql+psycopg"
    assert url.password == "encoded@value"
    assert url.query["sslmode"] == "require"
