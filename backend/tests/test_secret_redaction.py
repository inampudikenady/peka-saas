import pytest

from app.services.secret_redaction import SecretRedactionService


@pytest.mark.parametrize(
    ("value", "marker"),
    [
        ("password=hunter2", "[REDACTED PASSWORD]"),
        ("passwd: secret-value", "[REDACTED PASSWORD]"),
        ("api_key=sk-private-value", "[REDACTED SECRET]"),
        ("Authorization: Bearer abcdefghijklmnopqrstuvwxyz", "[REDACTED TOKEN]"),
        (
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.signaturevalue",
            "[REDACTED TOKEN]",
        ),
        ("AKIAIOSFODNN7EXAMPLE", "[REDACTED ACCESS KEY]"),
        (
            "postgresql://admin:private@db.internal/peka",
            "[REDACTED PASSWORD]",
        ),
        ("https://admin:private@example.test/path", "[REDACTED PASSWORD]"),
        (
            "-----BEGIN OPENSSH PRIVATE KEY-----\nprivate\n"
            "-----END OPENSSH PRIVATE KEY-----",
            "[REDACTED PRIVATE KEY]",
        ),
        ("CLIENT_SECRET=private-value", "[REDACTED SECRET]"),
    ],
)
def test_secret_categories_are_redacted(value, marker):
    result = SecretRedactionService().redact(value)
    assert marker in result.text
    assert "private-value" not in result.text
    assert result.redacted


@pytest.mark.parametrize(
    "value",
    [
        "Connect to 10.10.2.14 on port 5432.",
        "Use username deployer with document 0f9d3d72-8925-4a22-bf0f-20d0133a6348.",
        "Run ssh operator@example.test.",
        "The token count is 512.",
    ],
)
def test_normal_infrastructure_values_are_not_false_positives(value):
    result = SecretRedactionService().redact(value)
    assert result.text == value
    assert not result.redacted


def test_detection_can_only_be_disabled_by_server_configuration():
    value = "password=development-only"
    assert SecretRedactionService(enabled=False).redact(value).text == value
